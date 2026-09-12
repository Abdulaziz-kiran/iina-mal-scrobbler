"""Regression tests for Lua script event handling and single-attempt guard."""

import shutil
import subprocess
from pathlib import Path
import pytest

LUA_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "mal_scrobbler.lua"

MOCK_LUA_HARNESS = """
-- Mock mp environment
local registered_events = {}
local property_observers = {}
local subprocess_calls = 0

mp = {
    utils = {
        file_info = function(path) return { is_file = true } end,
        parse_json = function(str)
            return { status = "parse_failed", reason = "Test failure" }
        end,
    },
    msg = {
        info = function(...) end,
        warn = function(...) end,
        error = function(...) end,
    },
    osd_message = function(...) end,
    register_event = function(name, fn)
        registered_events[name] = fn
    end,
    observe_property = function(name, type, fn)
        property_observers[name] = fn
    end,
    get_property = function(name)
        if name == "path" then return "/anime/[Group] Frieren - 05.mkv" end
        return nil
    end,
    command_native_async = function(cmd, cb)
        subprocess_calls = subprocess_calls + 1
        -- simulate immediate asynchronous callback completion
        cb(true, { stdout = '{"status": "parse_failed", "reason": "test"}' }, nil)
    end
}

package.preload["mp.utils"] = function() return mp.utils end
package.preload["mp.msg"] = function() return mp.msg end

-- Load target script
dofile([==[%s]==])

-- 1. Simulate file-loaded
assert(registered_events["file-loaded"], "file-loaded not registered")
registered_events["file-loaded"]()

-- 2. Simulate position observer sequence: 80%% -> 81%% -> 82%% -> 83%%
local pos_fn = property_observers["percent-pos"]
assert(pos_fn, "percent-pos observer not registered")

pos_fn("percent-pos", 80.0)
pos_fn("percent-pos", 81.0)
pos_fn("percent-pos", 82.0)
pos_fn("percent-pos", 83.0)

-- Subprocess must be called exactly ONCE even though parse_failed occurred!
assert(subprocess_calls == 1, "Expected 1 subprocess call, got " .. tostring(subprocess_calls))

-- 3. Simulate file change: new file loaded
registered_events["file-loaded"]()
pos_fn("percent-pos", 80.0)

-- Should trigger again for the new file
assert(subprocess_calls == 2, "Expected 2 subprocess calls after file change, got " .. tostring(subprocess_calls))

print("LUA_TEST_OK")
"""

def test_lua_single_attempt_execution():
    lua_bin = shutil.which("luajit") or shutil.which("lua")
    if not lua_bin:
        pytest.skip("Neither luajit nor lua found in PATH")

    harness = MOCK_LUA_HARNESS % str(LUA_SCRIPT_PATH)
    proc = subprocess.run(
        [lua_bin, "-e", harness],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.returncode == 0, f"Lua test failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    assert "LUA_TEST_OK" in proc.stdout


STALE_CALLBACK_LUA_HARNESS = """
-- Mock mp environment
local registered_events = {}
local property_observers = {}
local subprocess_calls = 0
local async_callbacks = {}
local osd_messages = {}
local current_path = "/anime/File_A.mkv"

mp = {
    utils = {
        file_info = function(path) return { is_file = true } end,
        parse_json = function(str)
            return { status = "scrobbled", anime_title = "File A Anime", episode = 5 }
        end,
    },
    msg = {
        info = function(...) end,
        warn = function(...) end,
        error = function(...) end,
    },
    osd_message = function(text, duration)
        table.insert(osd_messages, text)
    end,
    register_event = function(name, fn)
        registered_events[name] = fn
    end,
    observe_property = function(name, type, fn)
        property_observers[name] = fn
    end,
    get_property = function(name)
        if name == "path" then return current_path end
        return nil
    end,
    command_native_async = function(cmd, cb)
        subprocess_calls = subprocess_calls + 1
        -- Queue callback to simulate delayed asynchronous completion
        table.insert(async_callbacks, cb)
    end
}

package.preload["mp.utils"] = function() return mp.utils end
package.preload["mp.msg"] = function() return mp.msg end

-- Load target script
dofile([==[__TARGET_SCRIPT_PATH__]==])

-- 1. File A loads
current_path = "/anime/File_A.mkv"
registered_events["file-loaded"]()

-- 2. File A reaches 80% and starts async scrobble
local pos_fn = property_observers["percent-pos"]
pos_fn("percent-pos", 80.0)
assert(subprocess_calls == 1, "File A should have started 1 subprocess")
assert(#async_callbacks == 1, "Callback for File A should be pending")

-- 3. File B loads BEFORE File A's callback completes!
current_path = "/anime/File_B.mkv"
registered_events["file-loaded"]()

-- 4. File A's delayed callback completes now!
local cb_A = table.remove(async_callbacks, 1)
cb_A(true, { stdout = '{"status": "scrobbled", "anime_title": "File A Anime", "episode": 5}' }, nil)

-- 5. Verify A's callback did not display OSD or mutate state for File B!
assert(#osd_messages == 0, "Stale callback should not have displayed OSD message on File B")

-- 6. File B reaches threshold and must launch its own scrobble subprocess!
pos_fn("percent-pos", 80.0)
assert(subprocess_calls == 2, "File B must still trigger its own subprocess (expected 2 calls, got " .. tostring(subprocess_calls) .. ")")

print("LUA_STALE_CALLBACK_TEST_OK")
"""


def test_lua_stale_async_callback_isolation():
    lua_bin = shutil.which("luajit") or shutil.which("lua")
    if not lua_bin:
        pytest.skip("Neither luajit nor lua found in PATH")

    harness = STALE_CALLBACK_LUA_HARNESS.replace("__TARGET_SCRIPT_PATH__", str(LUA_SCRIPT_PATH))
    proc = subprocess.run(
        [lua_bin, "-e", harness],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.returncode == 0, f"Lua stale callback test failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    assert "LUA_STALE_CALLBACK_TEST_OK" in proc.stdout

