-- iina-mal-scrobbler: Lightweight, asynchronous MyAnimeList scrobbler for IINA and mpv
-- Version: 0.1.0

local utils = require("mp.utils")
local msg = require("mp.msg")

-- Configuration
local SCROBBLE_THRESHOLD = 80.0  -- Percentage of video watched to trigger scrobble
local OSD_DURATION = 4.5         -- Seconds to display OSD notifications

-- Supported local video extensions
local VIDEO_EXTENSIONS = {
    [".mkv"] = true,
    [".mp4"] = true,
    [".avi"] = true,
    [".webm"] = true,
    [".m4v"] = true,
    [".ts"] = true,
    [".mov"] = true,
}

-- CLI binary candidate paths
local DEFAULT_CLI_PATHS = {
    os.getenv("HOME") .. "/.local/bin/mal-scrobbler",
    "/usr/local/bin/mal-scrobbler",
    "/opt/homebrew/bin/mal-scrobbler",
    "mal-scrobbler"
}

-- Per-file state tracking
local current_file_path = nil
local is_scrobbled = false
local is_processing = false

-- Resolve executable CLI path
local function get_cli_path()
    for _, path in ipairs(DEFAULT_CLI_PATHS) do
        if path:sub(1, 1) == "/" then
            local info = utils.file_info(path)
            if info and info.is_file then
                return path
            end
        else
            -- Plain command name in PATH
            return path
        end
    end
    return "mal-scrobbler"
end

-- Show user-friendly OSD message
local function notify_osd(text, duration)
    duration = duration or OSD_DURATION
    mp.osd_message(text, duration)
    msg.info("OSD: " .. text)
end

-- Check if path is a supported local video file
local function is_valid_local_video(path)
    if not path or path == "" then
        return false
    end

    -- Ignore remote streams / URLs
    if path:match("^https?://") or path:match("^ytdl://") or path:match("^edl://") then
        return false
    end

    local ext = path:match("(%.%w+)$")
    if not ext then
        return false
    end

    return VIDEO_EXTENSIONS[ext:lower()] == true
end

-- Trigger asynchronous scrobble subprocess
local function trigger_scrobble(path)
    if is_scrobbled or is_processing then
        return
    end

    is_processing = true
    local cli_cmd = get_cli_path()

    msg.info("Triggering scrobble for: " .. path .. " using " .. cli_cmd)

    local args = {
        cli_cmd,
        "scrobble",
        "--file",
        path,
        "--json"
    }

    mp.command_native_async({
        name = "subprocess",
        args = args,
        capture_stdout = true,
        capture_stderr = true,
        playback_only = false
    }, function(success, result, error_msg)
        is_processing = false

        if not success or not result then
            msg.error("Failed to execute mal-scrobbler CLI: " .. tostring(error_msg))
            notify_osd("⚠ MAL: Scrobbler CLI execution failed", 3.0)
            return
        end

        local stdout_raw = result.stdout or ""
        local res_json = utils.parse_json(stdout_raw)

        if not res_json then
            msg.error("mal-scrobbler returned non-JSON output: " .. stdout_raw)
            return
        end

        -- Evaluate response status and display appropriate notification
        local status = res_json.status
        local title = res_json.anime_title or "Anime"
        local ep = res_json.episode

        if status == "scrobbled" then
            is_scrobbled = true
            notify_osd(string.format("✓ MAL: %s (Ep. %s) updated!", title, tostring(ep or "?")), 5.0)
        elseif status == "already_synced" then
            is_scrobbled = true
            notify_osd(string.format("✓ MAL: %s (Ep. %s already synced)", title, tostring(ep or "?")), 3.0)
        elseif status == "pending" then
            is_scrobbled = true
            notify_osd("⏳ MAL offline: Progress queued for sync", 4.0)
        elseif status == "auth_required" then
            notify_osd("⚠ MAL: Login required (run 'mal-scrobbler auth login')", 6.0)
        elseif status == "ambiguous" then
            notify_osd("⚠ MAL: Ambiguous anime title match", 4.0)
        elseif status == "no_match" then
            notify_osd("✗ MAL: No match found for anime title", 3.5)
        elseif status == "parse_failed" then
            -- Silent or quiet OSD so we don't annoy users on non-anime files
            msg.info("Could not parse anime metadata: " .. (res_json.reason or ""))
        else
            msg.warn("Unexpected scrobbler status: " .. tostring(status))
        end
    end)
end

-- Playback position observer
local function on_percent_pos_change(name, percent)
    if not percent or is_scrobbled or is_processing then
        return
    end

    if percent >= SCROBBLE_THRESHOLD then
        if current_file_path and is_valid_local_video(current_file_path) then
            trigger_scrobble(current_file_path)
        end
    end
end

-- File loaded event handler
local function on_file_loaded()
    local path = mp.get_property("path")

    if path and is_valid_local_video(path) then
        current_file_path = path
        is_scrobbled = false
        is_processing = false
        msg.info("Loaded video file: " .. path)
    else
        current_file_path = nil
        is_scrobbled = true -- Prevent processing on unsupported streams
        is_processing = false
    end
end

-- Register mpv event hooks
mp.register_event("file-loaded", on_file_loaded)
mp.observe_property("percent-pos", "number", on_percent_pos_change)

msg.info("iina-mal-scrobbler Lua extension initialized.")
