# 페이퍼와이어 (PaperWire)

전 세계 신규 연구 논문을 매일 수집하여 한국어로 번역·요약하는 연구 동향 브리핑 사이트.

- 수집원 : OpenAlex(전 분야·전 언어) · arXiv · bioRxiv · medRxiv · Hugging Face Daily Papers
- 선별 : Gemini 로 후보 전체 제목 1차 평가(섹터 분류·중요도) → 13개 섹터별 상위 8편
- 요약 : 한국어 제목 · 헤드라인 · 배경/방법/결과 · 산업·투자 시사점 · 키워드 · 실용화 단계
- 갱신 : GitHub Actions 매일 10:17 KST 자동 실행 → GitHub Pages 배포

## 설정
Settings → Secrets and variables → Actions 에 등록
- `GEMINI_API_KEY` (필수)
- `OPENALEX_API_KEY` (선택, 무료)

수동 실행 : Actions → daily-papers → Run workflow
