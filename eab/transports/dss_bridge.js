/**
 * DSS (Debug Server Scripting) bridge for persistent C2000 debug sessions.
 *
 * Runs under TI's dss.sh and provides a JSON stdin/stdout protocol for
 * high-frequency memory read/write operations. Keeps the JTAG session
 * open for ~1-5ms per read (vs ~50ms with DSLite subprocess spawning).
 *
 * Usage: dss.sh dss_bridge.js <ccxml_path>
 *
 * Protocol (one JSON object per line):
 *   Input:  {"cmd": "read", "addr": 28674, "size": 4}
 *   Output: {"ok": true, "data": [18, 52, 86, 120]}
 *
 *   Input:  {"cmd": "write", "addr": 28674, "data": [18, 52]}
 *   Output: {"ok": true}
 *
 *   Input:  {"cmd": "halt"}
 *   Output: {"ok": true}
 *
 *   Input:  {"cmd": "resume"}
 *   Output: {"ok": true}
 *
 *   Input:  {"cmd": "reset"}
 *   Output: {"ok": true}
 *
 *   Input:  {"cmd": "quit"}
 *   Output: {"ok": true}  // then process exits
 */

importPackage(Packages.com.ti.debug.engine.scripting);
importPackage(Packages.java.io);
importPackage(Packages.java.lang);

var ccxml = arguments[0];

if (!ccxml) {
    print(JSON.stringify({"ok": false, "error": "Usage: dss.sh dss_bridge.js <ccxml_path>"}));
    java.lang.System.exit(1);
}

// Open debug session
var script = ScriptingEnvironment.instance();
script.traceSetConsoleLevel(TraceLevel.OFF);

var ds = script.getServer("DebugServer.1");
ds.setConfig(ccxml);

var debugSession = ds.openSession(".*");
debugSession.target.connect();

// Send ready signal
print(JSON.stringify({"ok": true, "status": "connected"}));
java.lang.System.out.flush();

// Read commands from stdin
var br = new BufferedReader(new InputStreamReader(java.lang.System["in"]));
var line;

while ((line = br.readLine()) !== null) {
    var response;
    try {
        var cmd = JSON.parse(line);

        switch (cmd.cmd) {
            case "read":
                // Read memory: 16-bit word reads, return as byte array
                // DSS readData(page, addr, bitSize, numWords)
                var wordCount = Math.ceil(cmd.size / 2);
                var words = debugSession.memory.readData(0, cmd.addr, 16, wordCount);
                // Convert 16-bit words to byte array (little-endian)
                var bytes = [];
                for (var i = 0; i < words.length && bytes.length < cmd.size; i++) {
                    bytes.push(words[i] & 0xFF);
                    if (bytes.length < cmd.size) {
                        bytes.push((words[i] >> 8) & 0xFF);
                    }
                }
                response = {"ok": true, "data": bytes};
                break;

            case "write":
                // Write memory: convert byte array to 16-bit words
                var writeWords = [];
                for (var j = 0; j < cmd.data.length; j += 2) {
                    var lo = cmd.data[j];
                    var hi = (j + 1 < cmd.data.length) ? cmd.data[j + 1] : 0;
                    writeWords.push(lo | (hi << 8));
                }
                debugSession.memory.writeData(0, cmd.addr, 16, writeWords);
                response = {"ok": true};
                break;

            case "halt":
                debugSession.target.halt();
                response = {"ok": true};
                break;

            case "resume":
                debugSession.target.run();
                response = {"ok": true};
                break;

            case "reset":
                debugSession.target.reset();
                response = {"ok": true};
                break;

            case "quit":
                response = {"ok": true};
                print(JSON.stringify(response));
                java.lang.System.out.flush();
                debugSession.target.disconnect();
                ds.stop();
                java.lang.System.exit(0);
                break;

            default:
                response = {"ok": false, "error": "Unknown command: " + cmd.cmd};
        }
    } catch (e) {
        response = {"ok": false, "error": String(e)};
    }

    print(JSON.stringify(response));
    java.lang.System.out.flush();
}

// Clean up on EOF
debugSession.target.disconnect();
ds.stop();
