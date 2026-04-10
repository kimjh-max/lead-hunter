# Epic-Studio "Generate failed: 400" 오류 분석 보고서

**작성일:** 2026-04-10
**대상:** `epic-studio-cpb.pages.dev/studio/`
**소스 파일:** `kv_studio_v2.html`
**담당:** Epi Agent (김병모)

---

## 1. 오류 발생 위치

```
사용자 동작: "가이드라인 생성 →" 버튼 클릭
에러 메시지: "Generate failed: 400"
```

### 호출 흐름

```
generateGuideline() (Line 1234)
  → analyzeReferences() (Line 1220)  ← 레퍼런스 7장 분석
    → callGemini(parts) (Line 1158)  ← 여기서 400 발생
      → Gemini API POST 요청
      → res.status === 400 → throw Error("API 400: ...")
  → addLog("가이드라인 생성 실패") (Line 1305)
  → showToast(err.message, 'err') (Line 1306)
```

---

## 2. 원인 분석

### 가장 유력한 원인: 레퍼런스 이미지 7장 Base64 → Gemini API 요청 크기 초과

**코드 (Line 1226):**
```javascript
const parts = refImages.map(img => ({
  inlineData: { mimeType: img.mime, data: img.base64 }
}));
parts.push({ text: prompt });
const result = await callGemini(parts, false);  // 7장 이미지 + 프롬프트 한 번에 전송
```

**문제:**
- 레퍼런스 이미지 7장이 **Base64 인코딩**되어 한 번의 API 요청에 모두 포함됨
- 이미지 1장당 평균 1~3MB × 7장 = **7~21MB의 Base64 데이터**
- Gemini API의 `generateContent` 요청 크기 제한: **20MB (일반) / 10MB (Flash 모델)**
- Base64 인코딩은 원본 대비 **약 33% 용량 증가** → 실제 15MB 이미지가 20MB로 전송

### 추가 가능 원인

| 원인 | 설명 | 확률 |
|------|------|------|
| **요청 크기 초과** | 7장 이미지 Base64 합산이 Gemini API 제한 초과 | **90%** |
| **이미지 해상도 초과** | Gemini는 이미지당 최대 해상도 제한 있음 (모델별 상이) | 30% |
| **API 키 문제** | 유효하지 않거나 해당 모델 권한 없음 | 10% |
| **모델명 오류** | `AppState.model` 값이 존재하지 않는 모델명 | 10% |
| **지원하지 않는 MIME 타입** | 일부 이미지 MIME 타입이 Gemini 미지원 | 5% |

---

## 3. 해결 방법

### 방법 1: 이미지 분할 처리 (권장)

`analyzeReferences()` 함수에서 이미지를 한 번에 보내지 말고, **2~3장씩 분할 분석 후 결과 병합:**

```javascript
// 수정 전 (Line 1220-1232)
async function analyzeReferences(refImages) {
  // ... 7장 한 번에 전송 → 400 에러
}

// 수정 후
async function analyzeReferences(refImages) {
  if (refImages.length === 0) return null;

  const BATCH_SIZE = 3;  // 3장씩 분할
  const batchResults = [];

  for (let i = 0; i < refImages.length; i += BATCH_SIZE) {
    const batch = refImages.slice(i, i + BATCH_SIZE);
    const batchNum = Math.floor(i / BATCH_SIZE) + 1;
    const totalBatches = Math.ceil(refImages.length / BATCH_SIZE);

    addLog(`레퍼런스 분석 중... (${batchNum}/${totalBatches})`);

    const prompt = `너는 비주얼 디자인 분석 전문가야.
첨부된 ${batch.length}장의 레퍼런스 이미지에서 공통 디자인 경향성을 JSON으로 추출해줘.
분석 항목: color_tendency, typography_tendency, layout_tendency, graphic_tendency, mood_tendency(키워드 3-5개), consistency_notes
JSON만 출력.`;

    const parts = batch.map(img => ({
      inlineData: { mimeType: img.mime, data: img.base64 }
    }));
    parts.push({ text: prompt });

    const result = await callGemini(parts, false);
    const analysis = parseGeminiJSON(result.map(p => p.text || '').join(''));
    batchResults.push(analysis);
  }

  // 결과 병합
  if (batchResults.length === 1) {
    setState('referenceAnalysis', batchResults[0]);
    return batchResults[0];
  }

  const mergePrompt = `아래 ${batchResults.length}개의 레퍼런스 분석 결과를 하나로 병합해줘.
공통점은 강화하고, 차이점은 종합하여 하나의 JSON으로 정리.
${JSON.stringify(batchResults, null, 2)}
JSON만 출력.`;

  const mergeResult = await callGemini([{ text: mergePrompt }], false);
  const merged = parseGeminiJSON(mergeResult.map(p => p.text || '').join(''));
  setState('referenceAnalysis', merged);
  return merged;
}
```

### 방법 2: 이미지 리사이즈 후 전송

업로드 시 이미지를 **1024px 이하로 리사이즈**하여 Base64 크기를 줄임:

```javascript
// handleImageUpload() 내에서 리사이즈 추가
async function resizeImage(base64, maxSize = 1024) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement('canvas');
      let { width, height } = img;
      if (width > maxSize || height > maxSize) {
        const ratio = Math.min(maxSize / width, maxSize / height);
        width = Math.round(width * ratio);
        height = Math.round(height * ratio);
      }
      canvas.width = width;
      canvas.height = height;
      canvas.getContext('2d').drawImage(img, 0, 0, width, height);
      resolve(canvas.toDataURL('image/jpeg', 0.85).split(',')[1]);
    };
    img.src = `data:image/jpeg;base64,${base64}`;
  });
}
```

### 방법 3: 에러 메시지 개선 (즉시 적용 가능)

현재 에러 메시지가 "Generate failed: 400"으로만 표시됨. Gemini API의 상세 에러를 표시하도록 수정:

```javascript
// callGemini() Line 1170-1175 수정
if (!res.ok) {
  const err = await res.json().catch(() => ({}));
  const msg = err?.error?.message || res.statusText;
  const detail = err?.error?.details?.[0]?.reason || '';

  if (res.status === 429) throw new Error('RATE_LIMIT: ' + msg);
  if (res.status === 400 && msg.includes('size')) {
    throw new Error('이미지 용량이 너무 큽니다. 레퍼런스 이미지 수를 줄이거나 해상도를 낮춰주세요.');
  }
  throw new Error(`API ${res.status}: ${msg} ${detail}`);
}
```

### 방법 4: generateGuideline()에서도 동일 문제 방지

Line 1290에서 CI 이미지도 한 번에 보내는 구조:

```javascript
const parts = ciImages.map(img => ({
  inlineData: { mimeType: img.mime, data: img.base64 }
}));
parts.push({ text: prompt });
```

CI 이미지 8장 + 긴 프롬프트(레퍼런스 분석 결과 포함)가 합쳐지면 역시 크기 초과 가능. **CI 이미지도 최대 3장으로 제한하거나 리사이즈 적용 필요.**

---

## 4. 즉시 조치 (테스트용)

에러를 우회하여 바로 테스트하려면:

1. **레퍼런스 이미지를 3장 이하로 줄여서** "가이드라인 생성" 재시도
2. 성공하면 → **방법 1(분할 처리)** 적용
3. 여전히 실패하면 → **F12 → Network → Response** 에서 Gemini API 상세 에러 확인

---

## 5. 권장 수정 우선순위

| 순위 | 항목 | 난이도 | 효과 |
|------|------|--------|------|
| 1 | 에러 메시지 상세화 (방법 3) | 5분 | 디버깅 즉시 가능 |
| 2 | 이미지 리사이즈 (방법 2) | 30분 | 근본 원인 해결 |
| 3 | 분할 분석 (방법 1) | 1시간 | 대량 이미지 지원 |
| 4 | CI 이미지 제한 (방법 4) | 15분 | 추가 에러 방지 |

---

## 6. 참고: Gemini API 제한 사항

| 항목 | 제한 |
|------|------|
| 요청 본문 크기 | 20MB (gemini-pro-vision), 10MB (flash) |
| 이미지 수 (1요청) | 최대 16장 |
| 이미지 해상도 | 모델별 상이 (보통 3072x3072 이내) |
| 분당 요청 수 (무료) | 15 RPM |
| 일일 요청 수 (무료) | 1,500 RPD |

---

*본 보고서에 대한 문의: 기술팀 타시르*
