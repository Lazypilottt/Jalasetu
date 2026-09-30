#!/usr/bin/env python3
"""Lightweight, resilient process watchdog and auto-restarter for JalaSetu services."""

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG %(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("watchdog")


class ServiceWatchdog:
    def __init__(self, cmd: list, health_url: str = None, log_file: str = None, check_interval: float = 5.0):
        self.cmd = cmd
        self.health_url = health_url
        self.log_file = log_file
        self.check_interval = check_interval
        self.process = None
        self.running = True
        self.consecutive_health_failures = 0
        self.restart_count = 0

        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)

    def _on_signal(self, signum, frame):
        logger.info(f"Received termination signal ({signum}). Shutting down managed process...")
        self.running = False
        self._stop_child()
        sys.exit(0)

    def _stop_child(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass

    def _start_child(self):
        log_out = None
        if self.log_file:
            log_out = open(self.log_file, "a", buffering=1)
        
        logger.info(f"Starting process: {' '.join(self.cmd)} (Restarts so far: {self.restart_count})")
        self.process = subprocess.Popen(
            self.cmd,
            stdout=log_out if log_out else subprocess.PIPE,
            stderr=subprocess.STDOUT if log_out else subprocess.PIPE,
            preexec_fn=os.setsid,
            env=os.environ.copy(),
        )
        self.consecutive_health_failures = 0
        logger.info(f"Managed process started with PID {self.process.pid}")

    def _check_health(self) -> bool:
        if not self.health_url:
            return True
        try:
            req = urllib.request.Request(self.health_url, headers={"User-Agent": "JalaSetu-Watchdog/1.0"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                return resp.status == 200
        except Exception as exc:
            logger.debug(f"Health check to {self.health_url} failed: {exc}")
            return False

    def run(self):
        self._start_child()
        time.sleep(2.0)

        while self.running:
            try:
                ret = self.process.poll()
                if ret is not None:
                    self.restart_count += 1
                    logger.warning(
                        f"Managed process PID {self.process.pid} died with return code {ret}! "
                        f"Auto-restarting in 2s (Restart #{self.restart_count})..."
                    )
                    time.sleep(2.0)
                    self._start_child()
                    time.sleep(2.0)
                    continue

                # Run health check if process is alive
                if self.health_url:
                    if self._check_health():
                        self.consecutive_health_failures = 0
                    else:
                        self.consecutive_health_failures += 1
                        logger.warning(
                            f"Health check failed ({self.consecutive_health_failures}/3) for {self.health_url}"
                        )
                        if self.consecutive_health_failures >= 3:
                            self.restart_count += 1
                            logger.error(
                                f"Process unresponsive after 3 consecutive health check failures. "
                                f"Killing and restarting (Restart #{self.restart_count})..."
                            )
                            self._stop_child()
                            time.sleep(1.0)
                            self._start_child()
                            time.sleep(2.0)
                            continue

                time.sleep(self.check_interval)

            except Exception as exc:
                logger.exception(f"Unexpected watchdog error: {exc}")
                time.sleep(self.check_interval)


def main():
    parser = argparse.ArgumentParser(description="JalaSetu Resilient Service Watchdog")
    parser.add_argument("--health-url", help="URL to ping for liveness checks (e.g. http://127.0.0.1:3000/health)")
    parser.add_argument("--log-file", help="Path to redirect process output")
    parser.add_argument("--interval", type=float, default=5.0, help="Health check interval in seconds")
    parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to run and supervise")

    args = parser.parse_args()
    if not args.cmd:
        parser.error("No command specified to supervise")

    cmd = args.cmd
    if cmd[0] == "--":
        cmd = cmd[1:]

    watchdog = ServiceWatchdog(
        cmd=cmd,
        health_url=args.health_url,
        log_file=args.log_file,
        check_interval=args.interval,
    )
    watchdog.run()


if __name__ == "__main__":
    main()
