# 크라켄 24시간 자동매매 봇 — 완전 설치·운영 가이드 (한국어)

이 저장소는 오픈소스 트레이딩 봇 **freqtrade**를 기반으로, 미국에서 합법적으로
사용 가능한 **Kraken(크라켄)** 거래소에서 24시간 자동매매를 돌리기 위한
프로젝트입니다. freqtrade 원본 코드는 전혀 수정하지 않았고, 모든 커스텀 기능은
설정 파일과 `companion`(동반 서비스)에 들어 있습니다.

---

## ⚠️ 시작 전 반드시 읽어주세요 (현실적인 기대치)

1. **$100~300으로 시작해서 단기간에 $10,000을 만드는 것은 현실적인 목표가
   아닙니다.** "목표 도달 → 출금 → 리셋" 기능은 요청하신 그대로 구현되어
   있지만, 대부분의 개인 자동매매 전략은 월 한 자릿수 % 수익(또는 손실)
   수준입니다. 봇은 도구일 뿐, 수익을 보장하지 않습니다.
2. **수수료가 소액 계좌의 최대 적입니다.** 크라켄 현물 수수료는 거래량이 적을 때
   편도 약 0.25~0.40%, 왕복 약 0.5~0.8%입니다. 이 봇의 기본 전략이 1시간봉의
   느린 매매를 쓰는 이유입니다.
3. **모의투자(dry-run)를 최소 2~4주 돌려보고** 승률·최대낙폭·수수료 대비 수익을
   확인한 뒤에 실전으로 전환하세요. 봇은 기본값이 모의투자 모드입니다.
4. **크라켄 API 키에 출금(Withdraw) 권한을 절대 주지 마세요.** 봇은 출금 기능이
   없고, 목표 금액 도달 시 "직접 출금하세요"라고 텔레그램으로 알려주기만 합니다.
   서버가 해킹되어도 자금 출금은 불가능하게 만드는 안전장치입니다.
5. **미국에서는 코인 매매 1건 1건이 모두 과세 대상입니다.** 그래서 이 봇에는
   CoinLedger 양식의 자동 세금 기록 기능이 들어 있습니다.

---

## 1. 준비물

| 준비물 | 설명 |
|---|---|
| VPS 1대 | 아래 5개 옵션 참고. 집 컴퓨터로도 가능(`local` 모드) |
| 크라켄 계정 | 본인인증(KYC) 완료 |
| 텔레그램 봇 2개 | [@BotFather](https://t.me/BotFather)에서 생성 (아래 설명) |
| 구글 계정 (권장) | 세금 기록용 구글 시트 자동 저장 |

### VPS 구매 옵션 5가지 (2026년 기준)

| # | 업체 | 가격 | 사양 | 평가 |
|---|---|---|---|---|
| 1 | **Oracle Cloud Always Free** | **무료** | ARM 최대 4코어/24GB | 최고 가성비. 단, 가입이 까다롭고 유휴 시 회수될 수 있음 |
| 2 | **RackNerd** | 연 $11~20 (프로모션) | 1~2.5GB RAM | 유료 중 최저가. 연말 프로모션 때 구매 |
| 3 | **Vultr** | 월 $2.5~6 | 1코어/1~2GB | 미국 데이터센터 다수, 시간 단위 과금 |
| 4 | **Hetzner** (미국 애슈번/힐스버러) | 월 약 $4.6 | 2코어/2GB NVMe | 달러당 성능 최고, 안정적 |
| 5 | **Contabo** | 월 약 €4.5 | 4코어/6GB | RAM 가성비 최고 (백테스트에 여유) |

**최소 사양**: 1 vCPU / 2GB RAM / 20GB 디스크 / Ubuntu 22.04 또는 24.04.
freqtrade는 x86과 ARM 도커 이미지를 모두 제공하므로 위 5개 전부 호환됩니다.
(`scripts/setup-vps.sh`가 스왑 2GB를 자동 생성합니다 — 크라켄 데이터 변환이
메모리를 많이 쓰기 때문입니다.)

### 텔레그램 봇 2개 만들기

1. 텔레그램에서 [@BotFather](https://t.me/BotFather) 검색 → `/newbot`
   - **봇 1**: freqtrade 알림/명령용 (예: `mykraken_trade_bot`)
   - **봇 2**: 설정 변경용 companion 봇 (예: `mykraken_settings_bot`)
   - 각각 발급되는 `123456:ABC-...` 형태의 **토큰**을 메모
2. [@userinfobot](https://t.me/userinfobot)에게 아무 메시지나 보내면 내
   **chat id**(숫자)를 알려줍니다. 메모하세요.
3. 새로 만든 봇 2개 모두에게 먼저 `/start`를 한 번 보내두세요.

---

## 2. 서버 설치

```bash
ssh root@내_VPS_IP
apt-get update && apt-get install -y git
git clone https://github.com/PineappleBingo/kraken-freqtrade-dev.git
cd kraken-freqtrade-dev
sudo bash scripts/setup-vps.sh
```

`setup-vps.sh`가 하는 일: Docker 설치, 스왑 2GB 생성, 방화벽(UFW)에서 SSH만
허용. FreqUI 웹 화면은 보안을 위해 외부에 열지 않습니다(아래 SSH 터널 참고).

> 💻 **집에 있는 컴퓨터/서버로 돌리는 경우**: Docker만 설치하고
> `settings.json`을 `"mode": "local"`로 바꾼 뒤 3단계로 진행하세요.
> `local` 모드에서는 같은 공유기(LAN) 안에서 `http://컴퓨터IP:8080`으로
> FreqUI에 바로 접속할 수 있습니다. VPS/로컬 전환은 이 파일 하나로 끝납니다.

---

## 3. 설정 파일 작성

```bash
cp .env.example .env
nano .env
```

| 항목 | 넣을 값 |
|---|---|
| `FREQTRADE__API_SERVER__PASSWORD` | 강한 비밀번호 (FreqUI 로그인용) |
| `FREQTRADE__API_SERVER__JWT_SECRET_KEY` / `WS_TOKEN` | 아무 긴 랜덤 문자열 |
| `FREQTRADE__TELEGRAM__ENABLED` | `true` |
| `FREQTRADE__TELEGRAM__TOKEN` | **봇 1** 토큰 |
| `FREQTRADE__TELEGRAM__CHAT_ID` | 내 chat id |
| `SETTINGS_BOT_TOKEN` | **봇 2** 토큰 |
| `SETTINGS_BOT_CHAT_IDS` | 내 chat id (여러 명이면 쉼표로 구분) |
| `FREQTRADE__EXCHANGE__KEY` / `SECRET` | **모의투자 중에는 비워두세요** |

### 구글 시트 세금 기록 연동 (권장, 약 10분, 무료)

1. [console.cloud.google.com](https://console.cloud.google.com) → 새 프로젝트
   → "API 및 서비스"에서 **Google Sheets API**와 **Google Drive API** 사용 설정
2. "IAM 및 관리자 → 서비스 계정" → 서비스 계정 생성 → 키 탭 → **JSON 키 추가**
   → 다운로드된 파일을 서버의 `config/google-service-account.json`로 저장
   (git에 올라가지 않도록 이미 제외되어 있습니다)
3. 구글 시트 새로 만들기 → 공유 → 서비스 계정 이메일
   (`...@...iam.gserviceaccount.com`)을 **편집자**로 추가
4. 시트 URL 중간의 긴 ID를 `.env`의 `GOOGLE_SHEETS_SPREADSHEET_ID`에 입력

이후 봇이 거래를 마칠 때마다:
- **모의투자 거래** → `PaperTrades` 탭 (세금 보고와 섞이지 않음)
- **실전 거래** → `Transactions` 탭 (CoinLedger Universal Import 양식 그대로 —
  세금 신고 시 CoinLedger에 바로 업로드 가능)
- 구글 연동과 무관하게 서버의 `companion_data/tax_log*.csv`에 **항상 백업**
  됩니다. 구글 전송이 실패하면 자동 재시도 대기열에 들어가 유실이 없습니다.

---

## 4. 실행 (모의투자 = 종이 거래)

```bash
bash scripts/start.sh     # settings.json의 vps/local 모드를 읽어 시작
bash scripts/status.sh    # 상태 확인
docker compose logs -f freqtrade   # 실시간 로그
```

기본 상태: **dry-run(모의투자) 모드, 가상 지갑 $300, 실시간 크라켄 시세**.
TradingView의 페이퍼 트레이딩과 같은 역할을 freqtrade가 자체 제공하는
것입니다. 실제 주문은 나가지 않습니다.

### 차트/대시보드 (FreqUI)

VPS 모드에서는 보안상 웹 화면이 서버 내부(127.0.0.1)에만 열립니다.
내 컴퓨터에서:

```bash
ssh -L 8080:127.0.0.1:8080 root@내_VPS_IP
```

를 켜둔 채 브라우저에서 `http://localhost:8080` 접속 → `.env`에 넣은
username/password로 로그인. 열린 포지션, 수익 곡선, 캔들 차트를 볼 수 있습니다.

### 텔레그램 사용법

**봇 1 (freqtrade)** — 매수/매도 알림이 자동으로 오고, 명령 버튼 키보드 제공:
`/status table` 열린 포지션, `/profit` 누적 수익, `/daily` 일별 수익,
`/balance` 잔고, `/stopentry` 신규 진입 중지, `/start` 재개

**봇 2 (설정 봇)** — `/start`를 보내면 인라인 버튼 메뉴가 열립니다:

```
⚙️ Kraken bot settings
├ 🛡 Risk      : 손절폭, 최대 동시 포지션, 운용 자본, 트레일링 스탑
├ 💰 Capital   : 목표 금액 / 확보 금액 / 리셋 자본 / 기능 on-off
├ 🤖 Bot control: 일시정지 / 재개 / 설정 리로드 / 현황
├ 📋 Failures  : 실패·취소된 주문 기록 (사후 분석용)
└ 🧾 Tax log   : 세금 기록 동기화 상태
```

버튼을 누르고 새 값을 메시지로 보내면 → 범위 검증 → 파일 저장 →
freqtrade에 즉시 반영(`reload_config`) → 변경 이력(audit log) 기록까지
자동으로 처리됩니다.

---

## 5. 위험관리 설정 (소액 $100~300 권장값)

모든 값은 `config/risk_settings.json` 한 파일에 모여 있고, 설정 봇으로도
바꿀 수 있습니다. 기본값(= 권장값):

| 설정 | 기본값 | 의미 |
|---|---|---|
| `max_open_trades` | 3 | 동시 최대 3개 포지션 (자본을 3분할) |
| `stake_amount` | unlimited | 가용 자본을 포지션 수로 자동 분배 |
| `available_capital` | 300 | 봇이 사용할 자본 상한 |
| `stoploss` | -8% | 개별 트레이드 손절 |
| `trailing_stop` | +4% 도달 후 2% 추적 | 수익 보호 |
| `minimal_roi` | 4% → 시간이 지나면 1%까지 완화 | 이익 실현 사다리 |
| StoplossGuard | 24시간 내 손절 4번 → 12시간 휴식 | 연속 손실 차단 |
| MaxDrawdown | 낙폭 10% → 24시간 휴식 | 계좌 보호 |
| CooldownPeriod | 청산 후 2캔들 대기 | 재진입 과열 방지 |

전략(`KrakenSpotStrategy`)은 1시간봉에서 EMA50 > EMA200 상승 추세일 때만
RSI 눌림목에 진입하는 보수적 추세추종형입니다. 거래 빈도가 낮아 수수료
부담이 적습니다.

---

## 6. 목표 도달 → 출금 → 리셋 (Capital Management)

요청하신 "1만 달러 도달 시 9천 확보, 1천으로 재시작" 기능입니다.
`config/risk_settings.json → companion.capital_management`:

```json
{
  "enabled": true,
  "profit_target_usd": 10000,   // 총 잔고가 이 금액에 도달하면
  "set_aside_usd": 9000,        // 이만큼은 직접 출금하고
  "restart_capital_usd": 1000,  // 봇은 이 금액으로만 다시 매매
  "force_exit_open_trades": false  // true면 도달 즉시 전 포지션 청산
}
```

동작 순서:
1. 총 잔고 ≥ 목표 금액 → 신규 진입 즉시 중지 (텔레그램 알림)
2. 열린 포지션이 모두 정리될 때까지 대기 (`force_exit`가 true면 즉시 청산)
3. 봇의 운용 자본을 `restart_capital_usd`로 리셋하고 매매 재개
4. **"크라켄에서 $9,000을 직접 출금하세요"** 텔레그램 알림 (봇은 절대 출금하지
   않습니다 — 보안 설계입니다)
5. 실제 출금으로 잔고가 줄어든 것이 확인되면 다음 목표를 향해 자동 재무장

기록은 `companion_data/capital_state.json`의 `bank_history`에 남습니다.

---

## 7. 실전 전환 (충분한 모의투자 후에!)

1. 크라켄 → Settings → API → 키 생성. 권한은 **Query Funds, Create & Modify
   Orders, Cancel Orders만.** ❌ Withdraw 금지
2. `.env`에 `FREQTRADE__EXCHANGE__KEY` / `SECRET` 입력
3. `config/config.json`에서:
   - `"dry_run": false`
   - `"db_url"`을 `sqlite:////freqtrade/user_data/tradesv3.live.sqlite`로 변경
     (모의투자 기록과 분리해 세금 기록을 깨끗하게 유지)
4. `config/risk_settings.json`의 `available_capital`을 실제 입금액으로
5. `bash scripts/start.sh` 로 재시작

실전 거래부터는 세금 기록이 구글 시트 `Transactions` 탭에 쌓입니다.

---

## 8. 문제 해결

| 증상 | 조치 |
|---|---|
| 봇이 안 뜸 | `docker compose logs freqtrade` — 설정 오류 메시지 확인 |
| 텔레그램 무반응 | 토큰/chat id 확인, 봇에게 `/start` 먼저 전송했는지 확인 |
| 주문 실패/취소가 잦음 | 설정 봇 → 📋 Failures 에서 원인 확인 (호가 스프레드, 최소 주문 금액 등) |
| Rate limit 오류 | `config.json`의 `ccxt_config.rateLimit`을 3100 → 5000으로 올리기 |
| 구글 시트에 안 올라감 | 설정 봇 → 🧾 Tax log에서 대기 행 확인; 서비스 계정을 시트에 편집자로 공유했는지 확인 |
| VPS 재부팅 후 | 자동 재시작됩니다(`restart: unless-stopped`). 안 되면 `bash scripts/start.sh` |
| 디스크/메모리 부족 | `docker system prune`, 스왑 확인 `free -h` |

모든 이벤트(체결·취소·오류)는 `companion_data/events.sqlite`에 남으므로
나중에 언제든 원인 분석이 가능합니다.

---

## 9. 백테스트 (선택)

크라켄 API는 과거 캔들을 720개까지만 주기 때문에 백테스트용 데이터는 체결
내역(trades)으로 내려받아야 합니다:

```bash
docker compose run --rm freqtrade download-data \
  --exchange kraken --dl-trades -t 1h --days 180 \
  -p BTC/USD ETH/USD SOL/USD
docker compose run --rm freqtrade backtesting \
  --strategy KrakenSpotStrategy -c /freqtrade/config/config.json \
  -c /freqtrade/config/risk_settings.json --timerange 20260101-
```

메모리를 많이 사용하니 RAM 2GB + 스왑 환경에서는 코인 수를 줄여서 받으세요.

---

## 10. 자주 묻는 질문

**Q. TradingView 페이퍼 트레이딩과 연동되나요?**
A. TradingView와 직접 연동되는 기능은 아니고, freqtrade의 dry-run 모드가
실시간 크라켄 시세로 같은 역할(모의투자)을 합니다. 차트는 FreqUI로 보시면
되고, TradingView 차트는 참고용으로 따로 보셔도 됩니다. (원하시면 나중에
TradingView 알림 → 웹훅 → 봇 진입 연동을 추가로 구현할 수 있습니다.)

**Q. 봇을 잠깐 멈추고 싶어요.**
A. 설정 봇 → 🤖 Bot control → ⏸ Pause (신규 진입만 중지, 기존 포지션은 관리
계속). 완전 종료는 `bash scripts/stop.sh`.

**Q. 설정을 파일로 직접 고쳐도 되나요?**
A. 네. `config/risk_settings.json` 수정 후 텔레그램 봇 1에서 `/reload_config`
를 보내거나 설정 봇의 🔄 Reload config 버튼을 누르면 반영됩니다.
