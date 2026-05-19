/**
 * PM2: chạy API health và (tùy chọn) watcher bằng Python trong `.venv`.
 *
 * Cài: npm install -g pm2
 * Chạy tất cả: pm2 start ecosystem.config.cjs
 * Chỉ API:     pm2 start ecosystem.config.cjs --only healthcheck-api
 * Chỉ watcher: pm2 start ecosystem.config.cjs --only healthcheck-watcher
 */
const path = require("path");

const root = __dirname;
const isWin = process.platform === "win32";
const python = isWin ? path.join(root, ".venv", "Scripts", "python.exe") : path.join(root, ".venv", "bin", "python");

const logsDir = path.join(root, "logs");

module.exports = {
  apps: [
    {
      name: "healthcheck-api",
      cwd: root,
      script: python,
      args: ["-m", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", process.env.PORT || "8010"],
      env: {
        NODE_ENV: "production",
      },
      // PM2: stdout / stderr của process (uvicorn access log + lỗi khởi động)
      out_file: path.join(logsDir, "pm2-healthcheck-api-out.log"),
      error_file: path.join(logsDir, "pm2-healthcheck-api-error.log"),
      merge_logs: false,
      time: true,
    },
    {
      name: "healthcheck-watcher",
      cwd: root,
      script: python,
      args: ["-m", "watcher.poller", "--config", "watcher/config.yaml"],
      env: {
        NODE_ENV: "production",
      },
      out_file: path.join(logsDir, "pm2-healthcheck-watcher-out.log"),
      error_file: path.join(logsDir, "pm2-healthcheck-watcher-error.log"),
      merge_logs: false,
      time: true,
      autorestart: true,
    },
  ],
};
