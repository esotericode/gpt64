-- BizHawk 2.11.1 APIs. Receives data, never executable commands.
local config = ...
assert(type(config) == "table" and type(config.root) == "string", "Load generated start.lua")
local root = config.root
local buttons = {"A", "B", "Z", "Start", "L", "R", "C Up", "C Down", "C Left", "C Right"}
local session = string.format("%x-%08x-%08x", os.time(), math.random(0, 0x7fffffff), math.random(0, 0x7fffffff))
local boolean_controls = {}
local last_id = nil

local function json(value)
    if type(value) == "string" then
        return '"' .. value:gsub('[%z\1-\31\\"]', function(c)
            return string.format("\\u%04x", string.byte(c))
        end) .. '"'
    elseif type(value) == "boolean" or type(value) == "number" then
        return tostring(value)
    elseif type(value) == "table" then
        local out = {}
        if #value > 0 then
            for _, v in ipairs(value) do out[#out + 1] = json(v) end
            return "[" .. table.concat(out, ",") .. "]"
        end
        for k, v in pairs(value) do out[#out + 1] = json(k) .. ":" .. json(v) end
        return "{" .. table.concat(out, ",") .. "}"
    end
    error("Unsupported JSON value")
end

local function publish(name, value)
    local destination = root .. "/" .. name
    local temporary = destination .. ".tmp"
    local f = assert(io.open(temporary, "wb"))
    assert(f:write(json(value)))
    assert(f:close())
    -- Windows Lua rename cannot overwrite an existing destination. Readers
    -- tolerate the brief missing-file interval; they never see a partial file.
    os.remove(destination)
    assert(os.rename(temporary, destination))
end

local function release()
    local neutral = {}
    for name, _ in pairs(boolean_controls) do neutral[name] = false end
    joypad.set(neutral, 1)
    joypad.setanalog({["X Axis"] = 0, ["Y Axis"] = 0}, 1)
    client.pause()
end

local function integer(value, low, high)
    local n = tonumber(value)
    assert(n and n % 1 == 0 and n >= low and n <= high, "Invalid action number")
    return n
end

local function parse(text)
    local lines = {}
    for line in text:gmatch("([^\n]*)\n") do lines[#lines + 1] = line:gsub("\r$", "") end
    assert(lines[1] == "GPT64 1", "Invalid protocol")
    assert(lines[2] == session, "Stale session; request not executed")
    local id = lines[3]
    assert(id and #id == 32 and id:match("^[0-9a-f]+$"), "Invalid request ID")
    local count = integer(lines[4], 0, 16)
    assert(#lines == count + 4 and text:sub(-1) == "\n", "Invalid request length")
    local segments, total = {}, 0
    for i = 1, count do
        local f, x, y, mask = lines[i + 4]:match("^(%d+) (-?%d+) (-?%d+) (%d+)$")
        local segment = {frames = integer(f, 1, 120), x = integer(x, -80, 80),
                         y = integer(y, -80, 80), mask = integer(mask, 0, 1023)}
        total = total + segment.frames
        assert(total <= 240, "Sequence too long")
        segments[#segments + 1] = segment
    end
    return id, segments, total
end

local function run_action(id, segments, total)
    local before = emu.framecount()
    local advanced = 0
    for _, segment in ipairs(segments) do
        local pressed = {}
        for name, _ in pairs(boolean_controls) do pressed[name] = false end
        for bit, name in ipairs(buttons) do
            pressed[name] = (segment.mask & (1 << (bit - 1))) ~= 0
        end
        for _ = 1, segment.frames do
            joypad.set(pressed, 1)
            joypad.setanalog({["X Axis"] = segment.x, ["Y Axis"] = segment.y}, 1)
            -- frameadvance yields until a frame happens; it does not itself
            -- unpause BizHawk. Resume explicitly, then pause when Lua resumes.
            client.unpause()
            emu.frameadvance()
            client.pause()
            advanced = advanced + 1
            assert(emu.framecount() == before + advanced, "Unexpected frame advancement")
        end
    end
    release()
    local after = emu.framecount()
    assert(after - before == total and client.ispaused(), "Frame/pause invariant failed")
    local filename = id .. ".png"
    client.screenshot(root .. "/images/" .. filename)
    local image = assert(io.open(root .. "/images/" .. filename, "rb"), "Screenshot not written")
    assert(image:read(8) == "\137PNG\r\n\26\n", "Screenshot is not a PNG")
    image:close()
    publish("responses/" .. id .. ".json", {id = id, session = session, ok = true, paused = true,
            frame_before = before, frame_after = after, advanced = total, image = filename})
end

local function main()
    client.pause()
    assert(emu.getsystemid() == "N64", "Load an N64 ROM before starting the bridge")
    local controls = joypad.get(1)
    assert(type(controls["X Axis"]) == "number" and type(controls["Y Axis"]) == "number",
           "Expected N64 X Axis and Y Axis controls")
    for name, value in pairs(controls) do
        if type(value) == "boolean" then boolean_controls[name] = true end
    end
    for _, name in ipairs(buttons) do assert(boolean_controls[name], "Missing controller button: " .. name) end
    client.clearautohold()
    client.setscreenshotosd(false)
    client.frameskip(0)
    release()
    publish("ready.json", {version = 1, session = session, system = "N64", buttons = buttons})
    console.log("gpt64 bridge ready: " .. root)
    while true do
        client.pause()
        local f = io.open(root .. "/request.txt", "rb")
        if f then
            -- Read a bounded packet to prevent an accidental huge input file.
            local text = f:read(4097)
            f:close()
            assert(os.remove(root .. "/request.txt"))
            assert(text and #text <= 4096, "Request too large")
            local id, segments, total = parse(text)
            if id ~= last_id then
                local ok, err = pcall(run_action, id, segments, total)
                release()
                if not ok then
                    publish("responses/" .. id .. ".json", {id = id, session = session, ok = false, error = tostring(err)})
                    error(err)
                end
                last_id = id
            end
        end
        -- Yield services the UI while paused. Idle never calls frameadvance.
        emu.yield()
    end
end

event.onexit(function()
    release()
    os.remove(root .. "/ready.json")
end)
local ok, err = pcall(main)
release()
os.remove(root .. "/ready.json")
if not ok then console.log("gpt64 bridge stopped: " .. tostring(err)) end
