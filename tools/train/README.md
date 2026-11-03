# 학습 도구 (tools/train)

A.X 4.0 Light를 학습 서버(AWS g5.xlarge, A10G 24GB)에서 QLoRA로 학습하고, 데스크탑 Ollama에 올려 개발셋으로 전후를 비교하기까지 쓰는 스크립트다. 결정은 ADR-0033(학습은 반드시, 쓸지는 비교로)·ADR-0035(채택 규칙)·ADR-0010(AWS에 올리는 범위), 계획과 설정 근거는 `docs/rag/m2/1회차-학습-계획-20261103.md`.

| 파일 | 하는 일 |
|---|---|
| `data.py` | 학습 예시를 대화형 프롬프트·답 형식으로 바꾸고, 종류 비율대로 검증 몫을 고른다(같은 문서 묶음은 갈라지지 않게) |
| `train_qlora.py` | 4비트 원본 + LoRA 어댑터로 답 부분만 학습한다. 채팅 틀이 서빙 틀과 같은지, 예시가 최대 길이 안인지 먼저 확인한다 |
| `merge_adapter.py` | 어댑터를 bf16 원본에 합쳐 Hugging Face 폴더로 저장한다(GPU에서) |
| `../../deploy/models/convert.sh` | 합친 폴더를 운영 모델과 같은 도구(llama.cpp b11312)로 4비트 GGUF로 바꾼다(`SOURCE_DIR`) |
| `../../deploy/models/import.sh` | 데스크탑 Ollama에 등록하고 채팅 틀을 확인한다 |

## 1. 학습 서버 준비(한 번)

학교 와이파이는 바깥 22번 포트를 막고, 학교 계정은 보안 그룹을 바꾸지 못한다. 그래서 서버를 Tailscale로 맥북과 같은 tailnet에 붙여 그 주소로 접속한다. 처음 한 번은 다른 경로로 서버에 들어가 Tailscale을 깔고 붙인다. 그 뒤로는 서버를 켜면 저절로 붙는다.

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --hostname aws-train
```

맥북 `~/.ssh/config`에 `Host aws-train`(서버의 Tailscale 주소, `User ubuntu`, 키 파일)을 두고 `ssh aws-train`으로 접속한다. 아래는 학습 서버에서 실행한다.

Deep Learning AMI(PyTorch 2.13, Ubuntu 26.04)는 PyTorch를 `/opt/pytorch` 가상환경(Python 3.13)에 둔다. 시스템 Python(3.14)에는 없다. 이 환경에 학습 라이브러리를 고정 목록 그대로 `--no-deps`로 더한다. 의존성을 pip에 맡기면 PyTorch가 요구하는 cuBLAS 13.1이 AMI의 cuBLAS 13.8 자리(pip 기록 없이 깔린 파일)를 덮어써, peft가 불러오는 TransformerEngine이 깨진다.

```bash
git clone https://github.com/QyongGin/DocuMind.git ~/DocuMind
cd ~/DocuMind && git checkout develop
source /opt/pytorch/bin/activate
pip install --no-deps -r tools/train/requirements.txt
python -c "import torch, peft, trl; print(torch.cuda.get_device_name(0))"
python -c "from huggingface_hub import snapshot_download; snapshot_download('skt/A.X-4.0-Light', revision='ba21c20ea1b31ded1ec3e2fb432335077dc4be98', local_dir='$HOME/models/ax40light')"
```

원본 커밋은 운영 모델(`deploy/models/ax40light/recipe.env`)과 같다. 다른 커밋으로 학습하면 전후 비교에 원본 차이가 섞인다. 원본(14GB) 내려받기는 약 7분 걸렸다(2026-11-03).

## 2. 학습 데이터 올리기(맥북)

AWS에는 학습 몫만 올린다(ADR-0010). 1회차 파일은 반출 범위 검사를 통과했다(`docs/rag/m2/1회차-준비-작업계획-20261101.md` §6).

```bash
ssh aws-train "mkdir -p ~/data"
scp Assets/train/round1/round-ga.jsonl aws-train:~/data/
```

## 3. 한 바퀴 시험(학습 서버)

20개로 10걸음만 학습해 합치기와 변환까지 막히는 곳이 없는지 본다.

```bash
cd ~/DocuMind/tools/train
python train_qlora.py --model ~/models/ax40light --data ~/data/round-ga.jsonl --out ~/runs/smoke --limit 20 --max-steps 10
python merge_adapter.py --model ~/models/ax40light --adapter ~/runs/smoke/adapter --out ~/merged/smoke
cd ~/DocuMind
MODEL_VOLUME=$HOME/model_work_smoke SOURCE_DIR=$HOME/merged/smoke deploy/models/convert.sh deploy/models/ax40light-r1
```

데스크탑에는 `OLLAMA_NAME=ax40light-smoke:q4km`으로 등록해(5절) 답 하나를 확인한다.

## 4. 본 학습(학습 서버)

180개를 3번 반복까지 학습하고, 검증 20개의 손실이 가장 낮은 반복의 체크포인트를 남긴다. 결과 폴더의 `run_manifest.json`에 설정, 데이터 SHA256, 라이브러리 판, 시간, 최대 GPU 메모리가 남는다.

```bash
cd ~/DocuMind/tools/train
python train_qlora.py --model ~/models/ax40light --data ~/data/round-ga.jsonl --out ~/runs/r1
python merge_adapter.py --model ~/models/ax40light --adapter ~/runs/r1/adapter --out ~/merged/ax40light-r1
cd ~/DocuMind
MODEL_VOLUME=$HOME/model_work SOURCE_DIR=$HOME/merged/ax40light-r1 deploy/models/convert.sh deploy/models/ax40light-r1
```

## 5. 데스크탑으로 옮겨 등록

맥북에서 받아 데스크탑으로 넘긴다(약 4.4GB).

```bash
scp aws-train:~/model_work/ax40light-r1/ax40light-r1-Q4_K_M.gguf ~/Downloads/
scp ~/Downloads/ax40light-r1-Q4_K_M.gguf desktop:~/
```

데스크탑 WSL, 저장소 루트에서 Ollama 볼륨에 넣고 등록한다(compose의 ollama가 떠 있어야 한다).

```bash
docker run --rm -v model_work:/work -v "$HOME":/in --entrypoint sh ollama/ollama:latest -c "mkdir -p /work/ax40light-r1 && cp /in/ax40light-r1-Q4_K_M.gguf /work/ax40light-r1/"
deploy/models/import.sh deploy/models/ax40light-r1
```

"채팅 틀 확인: 입력 토큰 6개, 공식 틀과 같다"가 나와야 한다.

## 6. 개발셋 전후 비교

데스크탑 WSL에서 AI 서버의 생성 모델만 바꿔 올린다. 프롬프트의 날짜 줄(오늘, 문서 게시일)을 반드시 켠다. 학습 예시의 입력과 학습 전 기준선이 모두 날짜 줄을 켠 모양이고, 설정 기본값은 꺼짐이다. 끄고 재면 입력 모양이 달라져 비교가 무효다(2026-11-03에 한 번 끄고 재서 다시 쟀다).

```bash
OLLAMA_LLM_MODEL=ax40light-r1:q4km AI_PROMPT_DATE_LINES_ENABLED=true DOCKER_CONFIG=~/.docker-nocreds docker compose --project-name documind_desktop -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.eval.yml --env-file .env up -d mysql chromadb ollama ai-server
```

같은 프롬프트에 온도 0이어도 Ollama(llama.cpp)는 직전 질문의 계산 재사용과 GPU 연산 순서 때문에 답 글자가 실행마다 조금씩 달라진다(2026-11-03: 프롬프트가 같은 개발셋 10문항 중 7문항의 답 글자가 전날 실행과 달랐다). 그래서 학습 전 모델도 같은 날 같은 서버 상태로 다시 재서 짝 비교하고, 학습 전 모델끼리 비교한 차이를 측정 잡음으로 함께 적는다.

맥북 `tools/corpus`에서 학습 전 기준선과 같은 날짜로 묻는다(`docs/development/local-gpu/평가-실행-절차.md`).

```bash
.venv/bin/python -m corpus evalset run --ai-url http://localhost:18000 --out ../../Assets/eval/runs/<날짜>-m2-train-r1 --index repro-20261010-develop15e776c --version v3 --ids "$(cat ../../Assets/eval/work/m2/dev_ids.txt)" --as-of 2026-10-31
```

학습 전 기준선은 `Assets/eval/runs/20261102-m2-s6-refusal-sentence-asof1031`이다. 판정이 갈린 문항은 두 답을 나란히 놓고 같은 기준으로 다시 판정한다(`docs/rag/m2/거절문장-기준선-20261102.md` §4).

## 7. 정리

학습 서버의 학교 데이터와 결과물을 지우고 인스턴스를 중지한다(콘솔에서).

```bash
rm -rf ~/data ~/runs ~/merged ~/model_work ~/model_work_smoke
```
