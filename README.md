# Memo Club

Flask + SQLite 메모 서비스. 실행 코드는 HTML/CSS를 포함해 `app.py` 하나이며,
회원가입·로그인·로그아웃, 개인 메모 CRUD, 관리자 회원 목록을 제공합니다.

## 실행 (PowerShell)

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt
$env:APP_ENV = 'development'
$env:SECRET_KEY = .\.venv\Scripts\python -c "import secrets; print(secrets.token_hex(32))"
$adminCredential = Read-Host '최초 admin 비밀번호 (12~128자)' -AsSecureString
$env:ADMIN_PASSWORD = [System.Net.NetworkCredential]::new('', $adminCredential).Password
.\.venv\Scripts\python app.py
```

접속: http://127.0.0.1:8000. 현재 개발 서버 설정은 `0.0.0.0:8000`입니다.
`.env`를 자동으로 읽지 않으므로 운영체제 환경변수 또는 배포 환경의 비밀 설정을 사용하세요.
실제 비밀번호와 키를 소스, 명령행 인자, Git에 넣지 마세요.

- `SECRET_KEY`: 매번 같은 강력한 무작위 값(최소 32자)을 안전하게 주입합니다.
  예시 명령은 새 키를 만들기 때문에 다시 실행하면 기존 쿠키가 무효화됩니다.
- `ADMIN_PASSWORD`: admin이 없는 DB의 최초 생성 시 필수입니다. 기본 비밀번호나 출력은 없습니다.
  기존 admin의 비밀번호는 환경변수 변경만으로 덮어쓰지 않습니다.
- 관리자 초기 메모는 최초 계정 생성 때 한 번만 만들어집니다.
  `SBOB{memo_club_admin_0915}`는 공개된 실습 식별자이며 실제 비밀로 사용하지 마세요.
- `/admin`은 관리자만 접근하며, 관리자도 다른 회원의 메모를 읽거나 수정할 수 없습니다.

## 운영 HTTPS

Docker는 Gunicorn의 `wsgi:app`을 사용합니다. `gunicorn.conf.py`는 sync worker 1개,
thread 1개로 지정해 SQLite의 import 시 초기화가 여러 worker에서 동시에 실행되지 않게 합니다.
개발용 `python app.py` 동작과 production에서의 직접 실행 거부는 그대로입니다.

Compose는 `APP_ENV=production`, `TRUSTED_HOSTS=0915.monster`를 명시합니다.
Caddy는 `0915.monster`의 자동 HTTPS와 HTTP→HTTPS 리디렉션을 담당하고 `app:8000`으로 전달합니다.
도메인의 DNS가 서버를 가리키고 외부에서 80/443에 접근할 수 있어야 실제 인증서 발급이 가능합니다.

`wsgi.py`는 production에서만 ProxyFix로 `X-Forwarded-Proto` 한 홉을 신뢰합니다.
Caddy는 이 헤더를 자신의 요청 scheme으로 덮어씁니다. Forwarded-For/Host/Port/Prefix는 신뢰하지 않습니다.
Gunicorn의 별도 프록시 헤더 해석도 꺼서 HTTPS 판정 경로를 이 미들웨어 하나로 제한합니다.
프록시 scheme이 없거나 HTTP이면 앱의 기존 production HTTP 거부가 유지됩니다.

이 신뢰 모델은 앱 포트를 호스트에 publish하지 않고 같은 Compose 네트워크의 Caddy만 앱에
접근하는 경계를 전제로 합니다. ProxyFix는 원격 주소 ACL이 아니므로 이 네트워크에 신뢰하지 않는
컨테이너를 추가하거나 앱 포트를 직접 공개하면 안 됩니다. Docker/호스트 관리자는 이 경계 밖입니다.
IP 전달 헤더는 이번 단계에서 변경하지 않았으므로 IP 제한은 계속 프록시 주소 단위로 적용될 수 있습니다.
`FLASK_DEBUG` 활성화는 거부하며 `flask --debug`나 외부 디버거 래퍼로 배포하지 마세요.

운영 쿠키는 `Secure`, `HttpOnly`, `SameSite=Lax`, `__Host-` 이름을 사용합니다.
개발 HTTP에서는 `Secure`만 끕니다. 세션은 로그인 후 절대 30분에 만료되고 활동으로 연장되지 않습니다.
로그아웃은 DB에서 세션을 취소하므로 이전 쿠키를 다시 보내도 인증되지 않습니다.

### 1차 배포 하드닝 범위

- H1: Linux Gunicorn 26.2.0, 단일 worker. Windows 개발 환경에는 환경 마커로 설치하지 않습니다.
- H2/H3: Caddy HTTPS 및 scheme 전용 1-hop 프록시 신뢰. `app.py`의 인증·인가·CSRF·세션 코드는 변경하지 않았습니다.
- H4: `.dockerignore`는 전체 제외 후 Dockerfile/requirements/app/wsgi/Gunicorn 설정만 허용합니다.
  Dockerfile도 실행 파일을 명시해 복사합니다. `.env`, `.git`, `.venv`, DB, 키, 백업, 테스트 파일은 포함하지 않습니다.
- H7: 공식 ssh-action v1.2.0에 대응하는 `7eaf76671a0d7eec5d98ee897acda4f968735a17`로 고정했습니다.
  릴리스와 커밋 매핑을 확인한 것이며 외부 Action의 모든 코드와 의존성을 보안 검증했다는 의미는 아닙니다.
  참고: https://github.com/appleboy/ssh-action/commit/7eaf76671a0d7eec5d98ee897acda4f968735a17

H5는 미처리입니다. 실제 DB는 여전히 `/app/memo.db`, 기존 볼륨은 `/app/data`입니다.
**현재 운영 컨테이너를 재생성하기 전에 DB 백업·이전을 별도 단계에서 완료해야 합니다.**
이번 변경으로 DB는 이미지에도 복사되지 않습니다. 이 단계에서는 배포·DB 이전·경로 변경을 수행하지 않습니다.
H6와 SSH fingerprint/배포 실패 제어/비루트 실행 등 Medium 이하 항목도 변경하지 않았습니다.

설정 검증:

```powershell
.\.venv\Scripts\python -m unittest -v test_contract test_security test_deployment
```

기존 21개 테스트는 그대로 실행합니다. 추가 테스트는 production WSGI 미들웨어를 임시 DB로 구동해
HTTPS 판정·쿠키·Host 검증·신뢰하지 않는 전달 헤더를 확인하고 Caddy/Compose/Docker/Gunicorn/Action 설정을 정적으로 검사합니다.
Docker가 있는 Linux 검증 환경에서는 별도로 `docker compose config --quiet`,
`docker compose run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`로 검증할 수 있습니다.
정적 검증과 Flask WSGI 테스트만으로 실제 Docker 부팅·외부 DNS·ACME 인증서 발급 성공까지 보장하지 않습니다.

## 테스트

```powershell
.\.venv\Scripts\python -m unittest -v test_security
```

표준 라이브러리 unittest와 Flask test client만 사용합니다. 각 실행은 임시 SQLite DB에서
작동하며 실제 `memo.db`와 계정·메모를 변경하지 않습니다.

## API 명세 기반 웹 UI

로그인 후 메모 목록 → 새 메모 작성 → 저장 → 상세 조회로 이동합니다.
기존 레트로 화면 안에서 fetch로 API를 호출하며 로딩·빈 목록·입력 오류·세션 만료를 안내합니다.
저장 실패 시 작성 중인 입력을 유지하고, 저장 중 중복 클릭을 막습니다.
기존 HTML 수정·삭제·회원가입·관리자 페이지도 계속 사용할 수 있습니다.

추가한 JSON API는 제공된 `API_SPEC.md`에 있는 아래 세 가지뿐입니다.

| 요청 | 응답 |
| --- | --- |
| GET /api/notes | 200, `{"notes": [...]}` |
| POST /api/notes | 201, 생성된 메모 객체 |
| GET /api/notes/정수ID | 200, 해당 메모 객체 |

메모 객체는 `id`, `title`, `body`, `created_at`, `updated_at`을 반환합니다.
DB의 기존 `content`를 API의 `body`로 매핑하므로 기존 메모도 그대로 조회됩니다.
JSON 생성 시 `body` 생략은 빈 문자열이며 제목 누락/공백은 400입니다.
API는 명세에 맞춰 비어 있지 않은 문자열 제목과 문자열 본문을 받으며 잘못된 타입은 400입니다.
명세에 없던 API 전용 100자/10,000자·제어 문자 제한은 제거했습니다.
기존 웹 폼의 길이·문자 검증과 전체 요청 본문 128 KiB 제한은 유지합니다.
인증되지 않은 `/api/*` 요청은 리디렉션 대신 JSON 401,
다른 작성자의 메모 또는 없는 메모는 JSON 404입니다. API 오류는 JSON으로 반환합니다.

로그인은 기존 `/login`과 세션 쿠키를 사용합니다. 브라우저 로그인 화면은 CSRF 토큰을 자동으로 포함합니다.
`Origin`, `Referer`, `Sec-Fetch-Site/Mode/Dest` 중 하나라도 있는 로그인 요청은 계속 토큰을 요구합니다.
이 브라우저 헤더가 모두 없고 토큰 필드도 없는 `POST /login`은 curl 같은 클라이언트의
username/password 로그인을 허용합니다. 토큰을 명시했는데 틀리면 헤더가 없어도 거부합니다.
이 예외는 로그인에만 적용하며 회원가입·로그아웃·기존 메모 HTML 폼은 항상 토큰이 필요합니다.
브라우저와 비브라우저를 완벽히 식별하는 방법은 아닙니다. Origin/Fetch Metadata를 보내는 현대 브라우저를
전제로 하며, 앞단 프록시가 이 헤더를 제거하지 않아야 합니다. 헤더를 모두 생략하는 레거시 브라우저는
무헤더 curl과 구분할 수 없습니다. User-Agent 문자열은 보안 판정에 사용하지 않습니다.
새 JSON API에는 명세에 없는 토큰 발급 API나 필수 CSRF 헤더를 추가하지 않았습니다.
쓰기 요청은 `application/json`만 허용합니다. API는 Origin/Fetch Metadata 값을 별도 인증 요건으로 사용하지 않습니다.
CORS 허용 헤더를 반환하지 않아 브라우저의 교차 출처 JSON 쓰기 프리플라이트도 허용하지 않습니다.
따라서 외부 클라이언트는 세션 쿠키와 JSON만으로 API를 사용할 수 있으며 Origin 헤더의 유무와 값으로 거부되지 않습니다.
이 방어를 유지하려면 API에 무분별한 CORS 허용이나 폼/text/plain JSON 파싱을 추가하면 안 됩니다.

### curl 원문 계약 테스트

```powershell
.\.venv\Scripts\python -m unittest -v test_contract test_security
```

`test_contract.py`는 기본적으로 사용자 Downloads의 `API_SPEC.md`에서 bash 코드 블록을 읽고
문구·헤더·URL·curl 옵션을 변경하지 않은 채 Git Bash에서 실행합니다.
다른 명세 경로는 `API_SPEC_PATH` 환경변수로 지정할 수 있습니다.
명세 명령을 실행하는 테스트이므로 검토한 명세 파일을 사용하세요.
포트 8000이 비어 있어야 하며, 기존 서버가 있으면 종료하거나 대체하지 않고 테스트가 실패합니다.
서버에서 상태코드를 관찰하므로 원문 curl에 `-w` 같은 옵션을 추가하지 않습니다.

| 원문 순서 | 수정 전 | 수정 후 |
| --- | --- | --- |
| POST /login | 400 | 302 + 세션 쿠키 |
| GET /api/notes | 401 | 200 + 빈 목록 |
| POST /api/notes | 401 | 201 + 생성 객체 |
| GET /api/notes/2 | 401 | 200 + 동일 객체 |

테스트는 임시 DB에 명세 전용 test/1234 계정을 준비합니다. 실제 DB나 회원가입의 비밀번호 정책은 변경하지 않습니다.
초기 관리자 메모가 ID 1을 차지하므로 예제로 생성한 메모가 ID 2가 됩니다.
실제 DB에서 그대로 실행하려면 해당 계정이 이미 존재해야 하며 ID 2가 해당 사용자의 메모여야 합니다.
이 데이터 전제는 API의 추가 인증 요건과 구분됩니다.

화면은 응답 텍스트를 `textContent`로 표시하고 CSP의 `connect-src 'self'`로 API 호출 출처를 제한합니다.
JavaScript 비활성화 시 기존 서버 렌더링 화면과 폼이 동작합니다.
기존 HTML 폼에서는 본문 필수 검증이 유지되며, 본문 생략은 새 JSON 생성 흐름에서 지원됩니다.

## 보안 검토 및 변경

### 수정 전 우선순위

| 우선순위 | 실제 확인된 문제 | 조치 |
| --- | --- | --- |
| 높음 | 로그인 요청 제한 없음 | SQLite의 원자적 카운터로 계정당 5회, IP당 30회/15분 제한 |
| 높음 | 서명 키가 DB에 저장되고 환경변수 없이도 실행됨 | SECRET_KEY 환경변수 필수화, DB 키 읽기·생성 제거 |
| 높음 | 초기 관리자 비밀번호가 터미널/로그에 출력됨 | ADMIN_PASSWORD 환경변수만 사용, 비밀번호 출력 제거 |
| 중간 | 7일 세션, 로그아웃해도 복사된 서명 쿠키 재사용 가능 | 30분 절대 만료 및 서버 측 세션 해시·폐기 상태 확인 |
| 중간 | CSP/프레임/콘텐츠 타입/리퍼러 보호 없음 | nonce 기반 CSP와 보안 헤더 적용 |
| 중간 | 운영 HTTPS/Host 정책이 명시되지 않음 | 운영 Secure/HSTS, Host 허용 목록, HTTP 거부 |
| 중간 | 존재하지 않는 계정은 해시 검사를 생략함 | 가짜 비밀번호 해시 검사 및 일반화된 오류 응답 |
| 낮음 | username 허용 문자, 제어 문자 검증 부족 | 회원가입 문자 허용 목록, 메모 길이·제어 문자 검증 |
| 낮음 | 매우 큰 정수 memo ID가 SQLite 변환 오류를 일으킬 수 있음 | SQLite 정수 범위를 벗어나면 404 |
| 낮음 | DB 보조 파일·여러 환경파일 등의 Git 제외 부족 | .gitignore 패턴 확장 |

### 이미 존재하여 유지한 방어

- SQL: 외부 값이 들어가는 모든 쿼리는 `?` 바인딩입니다. 고정 DDL/PRAGMA에는 외부 입력이 없습니다.
- XSS: 고정 Jinja 템플릿 자동 이스케이프. 메모의 HTML 문자는 텍스트로 저장·출력합니다.
  스크립트 문자열 저장 자체를 금지하는 방식이 아니라 실행되지 않도록 처리합니다.
- CSRF: 기존 HTML 회원가입·로그인·로그아웃·메모 쓰기에 토큰 확인. 새 JSON API 방어는 위 API 절을 참고하세요.
  관리자 페이지는 읽기만 지원하며 POST 관리자 작업은 없습니다.
- IDOR: 목록부터 수정·삭제 SQL까지 로그인 사용자 ID로 제한합니다. 다른 작성자의 메모는 404입니다.
- 관리자 권한: 매 요청 사용자와 권한을 DB에서 확인합니다. 쿠키의 is_admin/user_id 필드는 권한 결정에 사용하지 않습니다.
- 비밀번호: 해시만 저장하며 신규 해시 알고리즘을 scrypt로 명시했습니다. 기존 해시 로그인은 유지합니다.
- 리디렉션: 내부 url_for 경로만 사용하며 next/외부 목적지를 받지 않습니다.
- 경로: memo ID는 정수이며 파일 경로에 쓰지 않습니다. DB 경로는 고정이고 정적 파일 서빙도 비활성화했습니다.
- 삭제/로그아웃은 POST만 허용합니다. 회원가입 입력으로 관리자 권한을 지정할 수 없습니다.

### 추가 구현과 한계

- 로그인 성공 시 이전 세션을 폐기하고 인증 토큰·CSRF 토큰을 새로 생성합니다.
- 로그인 제한은 성공·실패를 포함한 시도를 집계합니다. 제한 응답은 429와 Retry-After를 반환합니다.
  계정/IP 카운터는 프로세스 간 공유되며 재시작 후에도 유지됩니다. 회원가입도 IP당 30회/15분입니다.
  원시 IP/계정명 대신 키 기반 HMAC 식별자를 저장합니다. 키를 교체하면 카운터 식별자도 바뀝니다.
- 중복 가입은 저장되지 않고 정상 가입과 같은 안내/리디렉션을 반환합니다.
  로그인 오류·가짜 해시는 계정 추측을 완화하지만 완벽한 처리시간 동일성까지 보장하지 않습니다.
- CSP는 unsafe-inline 없이 nonce로 기존 스타일과 삭제 확인 스크립트를 허용합니다.
- 예외 응답에는 DB 오류·스택·키를 포함하지 않습니다. 서버 로그에도 예외 종류만 기록합니다.
- 요청 본문 128 KiB, 폼 필드 수 10개로 제한합니다. 메모 제목 100자, 본문 10,000자입니다.
- Python/서버 프로세스를 직접 조작할 수 있는 운영자는 설정을 우회할 수 있으므로,
  앱 코드만으로 임의의 외부 디버거 실행까지 금지할 수는 없습니다.

### SQLite 및 Git 보존

검토 당시 Git 추적 파일에는 DB/환경파일이 없었습니다. 현재 SQLite quick_check 결과는 정상입니다.
기존 DB의 settings.secret_key 1건은 삭제 금지 요청에 따라 보존했지만 새 코드에서는 사용하지 않습니다.
반드시 기존 DB 키와 다른 새 SECRET_KEY를 사용하세요. 기존 키가 백업에 남아 있을 수 있습니다.
기존 DB를 삭제하거나 사용자/메모를 초기화하지 않으며, 다음 실행 때 필요한 테이블만 추가합니다.

DB에는 비밀번호 해시, 메모 본문, 인증 토큰의 SHA-256 해시, 만료/취소 정보 및 제한 카운터가 저장됩니다.
SQLite 자체 암호화는 적용하지 않았으므로 메모는 디스크에서 평문입니다.
DB/백업 디렉터리는 서비스 계정만 읽을 수 있도록 OS 권한과 디스크 암호화를 설정하세요.
만료된 인증 기록과 제한 카운터는 자동 삭제하지 않습니다. 장기 운영에서는 별도의 보존 정책이 필요합니다.
기존 관리자 비밀번호의 강제 재설정, Git 과거 이력의 비밀 정리, DB의 이전 키 제거는 수행하지 않았습니다.

설정 기준: https://flask.palletsprojects.com/en/stable/config/
