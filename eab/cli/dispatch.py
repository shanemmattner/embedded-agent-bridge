"""Command dispatch for eabctl CLI."""

from __future__ import annotations

import sys
from typing import Optional

from eab.cli.parser import _build_parser, _preprocess_argv
from eab.cli.helpers import _print


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for the ``eabctl`` CLI.

    Parses arguments, resolves the session base directory, and dispatches
    to the appropriate command handler.

    Args:
        argv: Argument list to parse.  Defaults to ``sys.argv[1:]``.

    Returns:
        Exit code: 0 on success, non-zero on error.
    """
    if argv is None:
        argv = sys.argv[1:]

    argv = _preprocess_argv(argv)

    # Late import to allow tests to monkeypatch eab.cli.cmd_xxx and eab.cli._resolve_base_dir
    import eab.cli as cli

    parser = _build_parser()
    args = parser.parse_args(argv)
    target_device = args.target_device
    base_dir = cli._resolve_base_dir(args.base_dir, device=target_device)

    if args.cmd == "devices":
        return cli.cmd_devices(json_mode=args.json)
    if args.cmd == "device":
        if args.device_action == "add":
            return cli.cmd_device_add(
                name=args.name,
                device_type=args.device_type,
                chip=args.chip,
                json_mode=args.json,
            )
        if args.device_action == "remove":
            return cli.cmd_device_remove(name=args.name, json_mode=args.json)

    if args.cmd == "status":
        return cli.cmd_status(base_dir=base_dir, json_mode=args.json)
    if args.cmd == "tail":
        lines = args.lines_flag if args.lines_flag is not None else (args.lines_pos if args.lines_pos is not None else 50)
        return cli.cmd_tail(base_dir=base_dir, lines=lines, json_mode=args.json)
    if args.cmd == "alerts":
        lines = args.lines_flag if args.lines_flag is not None else (args.lines_pos if args.lines_pos is not None else 20)
        return cli.cmd_alerts(base_dir=base_dir, lines=lines, json_mode=args.json)
    if args.cmd == "resets":
        lines = args.lines_flag if args.lines_flag is not None else (args.lines_pos if args.lines_pos is not None else 10)
        return cli.cmd_resets(base_dir=base_dir, lines=lines, json_mode=args.json)
    if args.cmd == "events":
        lines = args.lines_flag if args.lines_flag is not None else (args.lines_pos if args.lines_pos is not None else 50)
        return cli.cmd_events(base_dir=base_dir, lines=lines, json_mode=args.json)
    if args.cmd == "send":
        return cli.cmd_send(
            base_dir=base_dir,
            text=args.text,
            await_ack=args.await_ack,
            await_event=args.await_event,
            timeout_s=args.timeout,
            json_mode=args.json,
        )
    if args.cmd == "wait":
        return cli.cmd_wait(base_dir=base_dir, pattern=args.pattern, timeout_s=args.timeout, json_mode=args.json)
    if args.cmd == "wait-event":
        return cli.cmd_wait_event(
            base_dir=base_dir,
            event_type=args.event_type,
            contains=args.contains,
            command=args.command,
            timeout_s=args.timeout,
            json_mode=args.json,
        )
    if args.cmd == "pause":
        return cli.cmd_pause(base_dir=base_dir, seconds=args.seconds, json_mode=args.json)
    if args.cmd == "resume":
        return cli.cmd_resume(base_dir=base_dir, json_mode=args.json)
    if args.cmd == "openocd":
        if args.action == "status":
            return cli.cmd_openocd_status(base_dir=base_dir, json_mode=args.json)
        if args.action == "start":
            return cli.cmd_openocd_start(
                base_dir=base_dir,
                chip=args.chip,
                vid=args.vid,
                pid=args.pid,
                telnet_port=args.telnet_port,
                gdb_port=args.gdb_port,
                tcl_port=args.tcl_port,
                json_mode=args.json,
            )
        if args.action == "stop":
            return cli.cmd_openocd_stop(base_dir=base_dir, json_mode=args.json)
        if args.action == "cmd":
            if not args.command:
                _print({"error": "missing --command"}, json_mode=args.json)
                return 2
            return cli.cmd_openocd_cmd(
                base_dir=base_dir,
                command=args.command,
                telnet_port=args.telnet_port,
                timeout_s=args.timeout,
                json_mode=args.json,
            )
    if args.cmd == "gdb":
        if not args.commands:
            _print({"error": "missing --cmd (repeatable)"}, json_mode=args.json)
            return 2
        return cli.cmd_gdb(
            base_dir=base_dir,
            chip=args.chip,
            target=args.target,
            elf=args.elf,
            gdb_path=args.gdb_path,
            commands=args.commands,
            timeout_s=args.timeout,
            json_mode=args.json,
        )
    if args.cmd == "fault-analyze":
        return cli.cmd_fault_analyze(
            base_dir=base_dir,
            device=args.device,
            elf=args.elf,
            chip=args.chip,
            probe_type=args.probe,
            probe_selector=args.probe_selector,
            json_mode=args.json,
        )
    if args.cmd == "profile-function":
        return cli.cmd_profile_function(
            base_dir=base_dir,
            device=args.device,
            elf=args.elf,
            function=args.function,
            cpu_freq=args.cpu_freq,
            probe_type=args.probe,
            chip=args.chip,
            probe_selector=args.probe_selector,
            json_mode=args.json,
        )
    if args.cmd == "profile-region":
        return cli.cmd_profile_region(
            base_dir=base_dir,
            start_addr=args.start,
            end_addr=args.end,
            device=args.device,
            cpu_freq=args.cpu_freq,
            probe_type=args.probe,
            chip=args.chip,
            probe_selector=args.probe_selector,
            json_mode=args.json,
        )
    if args.cmd == "dwt-status":
        return cli.cmd_dwt_status(
            base_dir=base_dir,
            device=args.device,
            probe_type=args.probe,
            chip=args.chip,
            probe_selector=args.probe_selector,
            json_mode=args.json,
        )
    if args.cmd == "gdb-script":
        return cli.cmd_gdb_script(
            base_dir=base_dir,
            script_path=args.script_path,
            device=args.device,
            elf=args.elf,
            chip=args.chip,
            probe_type=args.probe,
            port=args.port,
            json_mode=args.json,
        )
    if args.cmd == "inspect":
        return cli.cmd_inspect(
            base_dir=base_dir,
            variable=args.variable,
            device=args.device,
            elf=args.elf,
            chip=args.chip,
            probe_type=args.probe,
            port=args.port,
            json_mode=args.json,
        )
    if args.cmd == "threads":
        return cli.cmd_threads(
            base_dir=base_dir,
            device=args.device,
            elf=args.elf,
            chip=args.chip,
            rtos=args.rtos,
            probe_type=args.probe,
            port=args.port,
            json_mode=args.json,
        )
    if args.cmd == "watch":
        return cli.cmd_watch(
            base_dir=base_dir,
            variable=args.variable,
            device=args.device,
            elf=args.elf,
            chip=args.chip,
            max_hits=args.max_hits,
            probe_type=args.probe,
            port=args.port,
            json_mode=args.json,
        )
    if args.cmd == "memdump":
        return cli.cmd_memdump(
            base_dir=base_dir,
            start_addr=args.start_addr,
            size=args.size,
            device=args.device,
            elf=args.elf,
            chip=args.chip,
            output_path=args.output_path,
            probe_type=args.probe,
            port=args.port,
            json_mode=args.json,
        )
    if args.cmd == "vars":
        return cli.cmd_vars(
            elf=args.elf,
            map_file=args.map_file,
            filter_pattern=args.filter_pattern,
            json_mode=args.json,
        )
    if args.cmd == "read-vars":
        if not args.var_names and not args.read_all:
            _print({"error": "Specify --var <name> or --all"}, json_mode=args.json)
            return 2
        return cli.cmd_read_vars(
            base_dir=base_dir,
            elf=args.elf,
            var_names=args.var_names,
            read_all=args.read_all,
            filter_pattern=args.filter_pattern,
            device=args.device,
            chip=args.chip,
            probe_type=args.probe,
            port=args.port,
            json_mode=args.json,
        )
    if args.cmd == "stream":
        if args.action == "start":
            return cli.cmd_stream_start(
                base_dir=base_dir,
                mode=args.mode,
                chunk_size=args.chunk,
                marker=args.marker,
                pattern_matching=not args.no_patterns,
                truncate=args.truncate,
                json_mode=args.json,
            )
        return cli.cmd_stream_stop(base_dir=base_dir, json_mode=args.json)
    if args.cmd == "recv":
        return cli.cmd_recv(
            base_dir=base_dir,
            offset=args.offset,
            length=args.length,
            output_path=args.output_path,
            base64_output=args.base64,
            json_mode=args.json,
        )
    if args.cmd == "recv-latest":
        return cli.cmd_recv_latest(
            base_dir=base_dir,
            length=args.length,
            output_path=args.output_path,
            base64_output=args.base64,
            json_mode=args.json,
        )
    if args.cmd == "start":
        return cli.cmd_start(
            base_dir=base_dir,
            port=args.port,
            baud=args.baud,
            force=args.force,
            json_mode=args.json,
            log_max_size_mb=args.log_max_size,
            log_max_files=args.log_max_files,
            log_compress=not args.no_log_compress,
            device_name=target_device or "",
        )
    if args.cmd == "stop":
        return cli.cmd_stop(json_mode=args.json, device_name=target_device or "")
    if args.cmd == "capture-between":
        return cli.cmd_capture_between(
            base_dir=base_dir,
            start_marker=args.start_marker,
            end_marker=args.end_marker,
            output_path=args.output,
            timeout_s=args.timeout,
            from_start=args.from_start,
            strip_timestamps=not args.no_strip_timestamps,
            filter_mode=args.filter,
            decode_base64=args.decode_base64,
            json_mode=args.json,
        )
    if args.cmd == "diagnose":
        return cli.cmd_diagnose(base_dir=base_dir, json_mode=args.json, device_name=device_name)
    if args.cmd == "flash":
        return cli.cmd_flash(
            firmware=args.firmware,
            chip=args.chip,
            address=args.address,
            port=args.port,
            tool=args.tool,
            baud=args.baud,
            connect_under_reset=getattr(args, "connect_under_reset", False),
            board=args.board,
            runner=args.runner,
            device=getattr(args, "device", None),
            reset_after=getattr(args, "reset_after", True),
            net_firmware=getattr(args, "net_firmware", None),
            no_stub=args.no_stub,
            extra_esptool_args=getattr(args, 'extra_esptool_args', []),
            json_mode=args.json,
        )
    if args.cmd == "erase":
        return cli.cmd_erase(
            chip=args.chip,
            port=args.port,
            tool=args.tool,
            connect_under_reset=getattr(args, "connect_under_reset", False),
            runner=args.runner,
            core=getattr(args, "core", "app"),
            json_mode=args.json,
        )
    if args.cmd == "chip-info":
        return cli.cmd_chip_info(
            chip=args.chip,
            port=args.port,
            json_mode=args.json,
        )
    if args.cmd == "reset":
        return cli.cmd_reset(
            chip=args.chip,
            method=args.method,
            connect_under_reset=getattr(args, "connect_under_reset", False),
            device=getattr(args, "device", None),
            json_mode=args.json,
        )
    if args.cmd == "preflight-hw":
        return cli.cmd_preflight_hw(
            base_dir=base_dir,
            chip=args.chip,
            stock_firmware=args.stock_firmware,
            address=args.address,
            timeout=args.timeout,
            json_mode=args.json,
        )
    if args.cmd == "decode-backtrace":
        return cli.cmd_decode_backtrace(
            elf=args.elf,
            text=args.text,
            arch=args.arch,
            toolchain=args.toolchain,
            show_raw=args.show_raw,
            json_mode=args.json,
        )
    if args.cmd == "rtt":
        if args.rtt_action == "start":
            return cli.cmd_rtt_start(
                base_dir=base_dir,
                device=args.device,
                transport=args.transport,
                interface=args.interface,
                speed=args.speed,
                channel=args.channel,
                block_address=args.block_address,
                probe_selector=args.probe_selector,
                json_mode=args.json,
            )
        if args.rtt_action == "stop":
            return cli.cmd_rtt_stop(
                base_dir=base_dir,
                json_mode=args.json,
            )
        if args.rtt_action == "status":
            return cli.cmd_rtt_status(
                base_dir=base_dir,
                json_mode=args.json,
            )
        if args.rtt_action == "reset":
            return cli.cmd_rtt_reset(
                base_dir=base_dir,
                wait=args.wait,
                json_mode=args.json,
            )
        if args.rtt_action == "tail":
            return cli.cmd_rtt_tail(
                base_dir=base_dir,
                lines=args.lines,
                json_mode=args.json,
            )

    if args.cmd == "rtt-capture":
        if args.rtt_capture_action == "start":
            channels = args.channels if args.channels else [1]
            return cli.cmd_rtt_capture_start(
                device=args.device,
                channels=channels,
                output=args.output,
                sample_width=args.sample_width,
                sample_rate=args.sample_rate,
                timestamp_hz=args.timestamp_hz,
                interface=args.interface,
                speed=args.speed,
                block_address=args.block_address,
                transport=args.transport,
                json_mode=args.json,
            )
        if args.rtt_capture_action == "convert":
            return cli.cmd_rtt_capture_convert(
                input_path=args.input,
                output_path=args.output,
                fmt=args.fmt,
                channel=args.channel,
                sample_rate=args.sample_rate,
                json_mode=args.json,
            )
        if args.rtt_capture_action == "info":
            return cli.cmd_rtt_capture_info(
                input_path=args.input,
                json_mode=args.json,
            )

    if args.cmd == "trace":
        if args.trace_action == "start":
            return cli.cmd_trace_start(
                output=args.output,
                source=args.source,
                device=args.device,
                channel=args.channel,
                trace_dir=args.trace_dir,
                logfile=args.logfile,
                json_mode=args.json,
            )
        if args.trace_action == "stop":
            return cli.cmd_trace_stop(json_mode=args.json)
        if args.trace_action == "export":
            return cli.cmd_trace_export(
                input_file=args.input,
                output_file=args.output,
                fmt=args.format,
                json_mode=args.json,
            )

    if args.cmd == "reg-read":
        from eab.cli.c2000 import cmd_reg_read
        return cmd_reg_read(
            chip=args.chip,
            register=args.register,
            group=args.group,
            ccxml=args.ccxml,
            json_mode=args.json,
        )
    if args.cmd == "erad-status":
        from eab.cli.c2000 import cmd_erad_status
        return cmd_erad_status(
            chip=args.chip,
            json_mode=args.json,
        )
    if args.cmd == "stream-vars":
        from eab.cli.c2000 import cmd_stream_vars
        if not args.var_specs:
            _print({"error": "Specify --var name:address:type"}, json_mode=args.json)
            return 2
        return cmd_stream_vars(
            map_file=args.map_file,
            var_specs=args.var_specs,
            interval_ms=args.interval,
            count=args.count,
            output=args.output,
            json_mode=args.json,
        )
    if args.cmd == "dlog-capture":
        from eab.cli.c2000 import cmd_dlog_capture
        if not args.buffer_specs:
            _print({"error": "Specify --buffer name:address"}, json_mode=args.json)
            return 2
        return cmd_dlog_capture(
            status_addr=args.status_addr,
            size_addr=args.size_addr,
            buffer_specs=args.buffer_specs,
            buffer_size=args.buffer_size,
            output=args.output,
            output_format=args.output_format,
            json_mode=args.json,
        )
    if args.cmd == "c2000-trace-export":
        from eab.cli.c2000 import cmd_c2000_trace_export
        return cmd_c2000_trace_export(
            output_file=args.output,
            erad_data=args.erad_data,
            dlog_data=args.dlog_data,
            log_file=args.log_file,
            process_name=args.process_name,
            json_mode=args.json,
        )

    if args.cmd == "multi":
        from eab.cli.multi_cmd import cmd_multi
        return cmd_multi(
            command_args=args.multi_cmd,
            timeout=args.timeout,
            json_mode=args.json,
        )
    if args.cmd == "size":
        from eab.cli.size_cmd import cmd_size
        return cmd_size(
            elf=args.elf,
            compare_elf=args.compare,
            json_mode=args.json,
        )
    if args.cmd == "defmt":
        if args.defmt_action == "decode":
            from eab.cli.defmt_cmd import cmd_defmt_decode
            return cmd_defmt_decode(
                elf=args.elf,
                input_file=args.input_file,
                base_dir=base_dir if getattr(args, 'from_rtt', False) else None,
                json_mode=args.json,
            )

    if args.cmd == "regression":
        from eab.cli.regression import cmd_regression
        return cmd_regression(
            suite=args.suite,
            test=args.test,
            filter_pattern=args.filter_pattern,
            timeout=args.timeout,
            json_mode=args.json,
        )

    parser.error(f"Unknown command: {args.cmd}")
    return 2
