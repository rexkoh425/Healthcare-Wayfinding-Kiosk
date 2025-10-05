#!/usr/bin/env node

const { spawn, spawnSync } = require('child_process');
const path = require('path');

const backendDir = path.join(__dirname, '..', 'backend');
const backendPort = process.env.BACKEND_PORT || '8000';
const pythonCandidates = process.env.PYTHON_CMD
  ? [process.env.PYTHON_CMD]
  : (process.platform === 'win32' ? ['python', 'python3', 'py'] : ['python3', 'python']);

function pickPython() {
  for (const cmd of pythonCandidates) {
    const check = spawnSync(cmd, ['--version'], { stdio: 'ignore' });
    if (check.status === 0) {
      return cmd;
    }
  }
  return null;
}

const pythonCmd = pickPython();
if (!pythonCmd) {
  console.error('[server] Could not find a Python interpreter (python3/python). Set PYTHON_CMD if it is installed in a custom location.');
  process.exit(1);
}

const envForPython = {
  ...process.env,
  PYTHONUNBUFFERED: '1',
};

const pythonArgs = ['-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', backendPort];
const shouldReload = process.env.BACKEND_RELOAD === '1' || (typeof process.env.BACKEND_RELOAD === 'undefined' && process.env.NODE_ENV !== 'production');
if (shouldReload) {
  pythonArgs.push('--reload');
}
const pythonProc = spawn(pythonCmd, pythonArgs, {
  cwd: backendDir,
  stdio: 'inherit',
  env: envForPython,
});

if (!pythonProc || !pythonProc.pid) {
  console.error('[server] Failed to launch FastAPI backend.');
  process.exit(1);
}

console.log('[server] FastAPI backend started using ' + pythonCmd + ' on port ' + backendPort);

const wsArgs = [path.join(__dirname, '..', 'index.js')];
const wsProc = spawn(process.execPath, wsArgs, {
  cwd: path.join(__dirname, '..'),
  stdio: 'inherit',
  env: process.env,
});

if (!wsProc || !wsProc.pid) {
  console.error('[server] Failed to launch WebSocket server.');
  pythonProc.kill('SIGTERM');
  process.exit(1);
}

console.log('[server] WebSocket server started on port ' + (process.env.PORT || '8080'));

const children = [
  { name: 'FastAPI backend', proc: pythonProc },
  { name: 'WebSocket server', proc: wsProc },
];

let exitScheduled = false;

function requestExit(code, signal) {
  const exitCode = typeof code === 'number' ? code : 0;
  const sig = signal || 'SIGTERM';
  if (exitScheduled) {
    return;
  }
  exitScheduled = true;
  children.forEach(({ proc, name }) => {
    if (proc.exitCode === null && !proc.killed) {
      try {
        proc.kill(sig);
      } catch (err) {
        if (!err || err.code !== 'ESRCH') {
          console.error('[server] Failed to forward ' + sig + ' to ' + name + ':', err);
        }
      }
    }
  });
  setTimeout(() => process.exit(exitCode), 500);
}

process.on('SIGINT', () => requestExit(0, 'SIGINT'));
process.on('SIGTERM', () => requestExit(0, 'SIGTERM'));

children.forEach(({ name, proc }) => {
  proc.on('exit', (code, signal) => {
    let status;
    if (code !== null) {
      status = 'code ' + code;
    } else if (signal) {
      status = 'signal ' + signal;
    } else {
      status = 'an unknown status';
    }
    console.log('[server] ' + name + ' exited with ' + status);
    requestExit(code === null ? 0 : code);
  });

  proc.on('error', (err) => {
    console.error('[server] ' + name + ' failed to start:', err);
    requestExit(1);
  });
});
