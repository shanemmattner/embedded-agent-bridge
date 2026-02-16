/**
 * CCS Scripting Debug Server — Persistent JSON-RPC over stdin/stdout
 *
 * Maintains a single debug session and accepts commands as JSON lines on stdin.
 * Returns JSON line responses on stdout.
 *
 * Usage:
 *   /path/to/ccs/scripting/run.sh debug_server.mjs <ccxml_path> [out_path]
 *
 * Commands (JSON on stdin):
 *   {"id":1, "cmd":"read_var",  "args":{"name":"test_enabled"}}
 *   {"id":2, "cmd":"write_var", "args":{"name":"test_enabled","value":1}}
 *   {"id":3, "cmd":"read_mem",  "args":{"address":"0xa840","count":1,"bitSize":16}}
 *   {"id":4, "cmd":"write_mem", "args":{"address":"0xa840","value":42}}
 *   {"id":5, "cmd":"halt"}
 *   {"id":6, "cmd":"run"}
 *   {"id":7, "cmd":"reset"}
 *   {"id":8, "cmd":"status"}
 *   {"id":9, "cmd":"load_program", "args":{"path":"/path/to/file.out"}}
 *   {"id":10,"cmd":"list_cores"}
 *   {"id":11,"cmd":"quit"}
 */

import { createInterface } from "readline";

// argv[0]=node, argv[1]=launcher.mjs, argv[2]=this_script, argv[3+]=args
const ccxmlPath = process.argv[3];
const outPath = process.argv[4] || null;

if (!ccxmlPath) {
    send({ type: "error", message: "Usage: debug_server.mjs <ccxml_path> [out_path]" });
    process.exit(1);
}

function send(obj) {
    process.stdout.write(JSON.stringify(obj) + "\n");
}

// --- Initialize CCS Scripting ---
let ds, session;
try {
    ds = initScripting();
    ds.setScriptingTimeout(15000);
    ds.configure(ccxmlPath);
    const { cores } = ds.listCores();

    // Open session — prefer C28xx, fall back to first core
    try {
        session = ds.openSession(/C28/);
    } catch (_) {
        session = ds.openSession();
    }

    session.target.connect();

    // Load .out for symbol resolution if provided
    if (outPath) {
        session.memory.loadProgram(outPath);
    }

    send({
        type: "ready",
        cores,
        ccxml: ccxmlPath,
        outFile: outPath || null,
    });
} catch (e) {
    send({ type: "error", message: `Init failed: ${e.message}` });
    process.exit(1);
}

// --- Command handlers ---
function handleCommand(cmd) {
    const id = cmd.id ?? null;
    const args = cmd.args || {};

    try {
        switch (cmd.cmd) {
            case "read_var": {
                session.target.halt();
                const val = session.expressions.evaluate(args.name);
                return { id, ok: true, name: args.name, value: Number(val) };
            }

            case "write_var": {
                session.target.halt();
                session.expressions.evaluate(`${args.name} = ${args.value}`);
                const verify = session.expressions.evaluate(args.name);
                return { id, ok: true, name: args.name, value: Number(verify) };
            }

            case "read_mem": {
                const addr = BigInt(args.address);
                const count = args.count || 1;
                const bitSize = args.bitSize || 16;
                if (count === 1) {
                    const val = session.memory.readOne(addr, bitSize);
                    return { id, ok: true, address: args.address, value: Number(val) };
                } else {
                    const vals = session.memory.read(addr, count, bitSize);
                    return { id, ok: true, address: args.address, values: vals.map(Number) };
                }
            }

            case "write_mem": {
                const addr = BigInt(args.address);
                const bitSize = args.bitSize || 16;
                session.memory.write(addr, args.value, bitSize);
                const verify = session.memory.readOne(addr, bitSize);
                return { id, ok: true, address: args.address, value: Number(verify) };
            }

            case "halt": {
                session.target.halt();
                return { id, ok: true, state: "halted" };
            }

            case "run": {
                // run() blocks until target halts — use short timeout + catch
                const prevTimeout = 15000;
                try {
                    ds.setScriptingTimeout(200);
                    session.target.run();
                    // If we get here, target halted within 200ms
                    ds.setScriptingTimeout(prevTimeout);
                    return { id, ok: true, state: "halted_quickly" };
                } catch (e) {
                    ds.setScriptingTimeout(prevTimeout);
                    if (e instanceof ScriptingTimeoutError) {
                        // Target is running (expected)
                        return { id, ok: true, state: "running" };
                    }
                    throw e;
                }
            }

            case "reset": {
                session.target.reset();
                return { id, ok: true, state: "reset" };
            }

            case "status": {
                return { id, ok: true, connected: true };
            }

            case "load_program": {
                session.memory.loadProgram(args.path);
                return { id, ok: true, loaded: args.path };
            }

            case "list_cores": {
                const { cores } = ds.listCores();
                return { id, ok: true, cores };
            }

            case "quit": {
                return { id, ok: true, action: "quit" };
            }

            default:
                return { id, ok: false, error: `Unknown command: ${cmd.cmd}` };
        }
    } catch (e) {
        return { id, ok: false, error: e.message };
    }
}

// --- stdin readline loop (top-level await keeps process alive) ---
const rl = createInterface({ input: process.stdin, terminal: false });

await new Promise((resolve) => {
    rl.on("line", (line) => {
        let cmd;
        try {
            cmd = JSON.parse(line);
        } catch (e) {
            send({ ok: false, error: `Invalid JSON: ${e.message}` });
            return;
        }

        const result = handleCommand(cmd);
        send(result);

        if (cmd.cmd === "quit") {
            rl.close();
        }
    });

    rl.on("close", () => {
        try {
            session.target.disconnect();
            ds.shutdown();
        } catch (_) {}
        resolve();
    });
});
