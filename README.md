# Health check + watcher

API nhẹ (`GET /health`) chạy trên **máy chủ** và **watcher** ping định kỳ từ **máy khác** (VPS / PC luôn bật) để log `last_ok`, `first_fail`, `recovered` — giúp ước lượng khoảng thời gian mất dịch vụ hoặc tắt máy.

## Môi trường (venv)

```text
python -m venv .venv
```

- Windows (PowerShell): `.\.venv\Scripts\Activate.ps1`
- Linux / WSL: `source .venv/bin/activate`

```text
pip install -r requirements.txt
```

## Chạy server (máy chủ công ty)

Từ thư mục gốc repo (đã kích hoạt `.venv`):

```text
python -m server.app
```

Hoặc:

```text
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

Biến môi trường:

- `HOST` (mặc định `0.0.0.0`) — chỉ dùng khi chạy `python -m server.app`
- `PORT` (mặc định `8000`)
- `HEALTHCHECK_TOKEN` (tùy chọn) — nếu đặt, client phải gửi `Authorization: Bearer <token>`

Triển khai lâu dài: Windows Service, NSSM, hoặc Task Scheduler để process luôn chạy cùng OS; nên đặt sau reverse proxy nội bộ (nginx, IIS) nếu có.

## Chạy bằng PM2

Yêu cầu: đã tạo `.venv` và `pip install -r requirements.txt`; cài PM2 (cần Node/npm):

```text
npm install -g pm2
```

Từ thư mục gốc repo:

```text
pm2 start ecosystem.config.cjs
```

Chỉ chạy API (không chạy watcher trên cùng máy):

```text
pm2 start ecosystem.config.cjs --only healthcheck-api
```

Lưu cấu hình khởi động lại máy (Linux/WSL thường dùng `pm2 startup` + `pm2 save`; Windows xem tài liệu PM2).

### Log sẽ nằm ở đâu?

Có **hai loại** log, không trùng nhau:

1. **Log do PM2 ghi** (mọi thứ in ra **stdout/stderr** của process): với file [`ecosystem.config.cjs`](ecosystem.config.cjs) hiện tại, chúng nằm trong thư mục **`logs/`** tại gốc repo:
   - `logs/pm2-healthcheck-api-out.log` — output chính của uvicorn (kể cả access log mặc định)
   - `logs/pm2-healthcheck-api-error.log` — stderr của API
   - `logs/pm2-healthcheck-watcher-out.log` / `logs/pm2-healthcheck-watcher-error.log` — tương tự cho watcher  
   Các dòng có thêm timestamp do `time: true` trong cấu hình PM2.

   Nếu bạn **không** chỉnh `out_file` / `error_file` trong ecosystem, PM2 mặc định ghi vào **`~/.pm2/logs/`** (trên Windows thường là `%USERPROFILE%\.pm2\logs\`), tên file dạng `<tên-app>-out.log` / `<tên-app>-error.log`.

2. **Log do watcher tự ghi trong Python** (sự kiện `last_ok`, `first_fail`, `recovered`, …): theo biến `LOG_PATH` hoặc khóa `log_path` trong YAML (mặc định **`watcher.log`** tại thư mục làm việc khi chạy, tức gốc repo nếu PM2 `cwd` là gốc repo). File này **không** thay thế log PM2; nên giữ cả hai nếu cần audit rõ ràng.

Gợi ý: `pm2 logs healthcheck-api` để xem trực tiếp trên terminal; `pm2 monit` để theo dõi CPU/RAM.

## Chạy watcher (máy **ngoài** server)

```text
python -m watcher.poller --config watcher/config.yaml
```

Hoặc chỉ dùng biến môi trường:

- `HEALTH_URL` — URL đầy đủ tới `/health`
- `INTERVAL_SEC` — chu kỳ giây (mặc định 30)
- `TIMEOUT_SEC` — timeout HTTP (mặc định 10)
- `LOG_PATH` — file log (mặc định `watcher.log`)
- `HEALTHCHECK_BEARER` — bearer khớp với `HEALTHCHECK_TOKEN` trên server (nếu có)

Cấu hình thực tế: [`watcher/config.yaml`](watcher/config.yaml) (PM2 và lệnh trên đều trỏ file này). Mẫu tham khảo: `watcher/config.example.yaml` — lần đầu clone có thể `copy watcher\config.example.yaml watcher\config.yaml` rồi sửa `health_url`, token. File `config.yaml` không commit nếu có secret (`bearer_token`).

File YAML có thể dùng khóa `bearer_token`; biến môi trường vẫn được ưu tiên khi cần override nhanh.

**Lưu ý:** Nếu watcher chạy trong WSL trên laptop hay ngủ/sleep, log có thể gián đoạn **không phải** do server tắt. Ưu tiên máy luôn bật (VPS, PC cố định, máy chủ giám sát).

## Bảo mật

- Không nên public `/health` ra internet nếu không cần; dùng VPN, allowlist IP, hoặc đặt `HEALTHCHECK_TOKEN` / TLS phía proxy.

## Điều tra tắt máy bất thường (Windows Server)

Health check chỉ cho **mốc thời gian**. Nguyên nhân nên đối chiếu **Event Viewer** → System (ví dụ Kernel-Power 41, shutdown 1074), UPS, nhiệt độ, v.v.
