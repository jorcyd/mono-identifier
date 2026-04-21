// MonoID — Monospace Font Identifier
// Frontend logic

// API base URL resolution:
//   1. window.MONOID_API (inline override, ex: `window.MONOID_API = "http://..."`)
//   2. <meta name="monoid-api" content="http://...">
//   3. same origin (empty string) if served alongside the backend
//   4. fallback: http://localhost:8000 for local dev
const API = (() => {
  if (typeof window !== "undefined" && window.MONOID_API) return window.MONOID_API;
  const meta = document.querySelector('meta[name="monoid-api"]');
  if (meta?.content) return meta.content.trim();
  if (location.origin && location.protocol !== "file:") return "";
  return "http://localhost:8000";
})();

// DOM Elements
const uploadZone = document.getElementById("upload-zone");
const fileInput = document.getElementById("file-input");
const previewContainer = document.getElementById("preview-container");
const previewImage = document.getElementById("preview-image");
const cropCanvas = document.getElementById("crop-canvas");
const cropContainer = document.getElementById("crop-container");
const cropHint = document.getElementById("crop-hint");
const btnClear = document.getElementById("btn-clear");
const btnResetCrop = document.getElementById("btn-reset-crop");
const btnAnalyze = document.getElementById("btn-analyze");
const uploadSection = document.getElementById("upload-section");
const loadingSection = document.getElementById("loading-section");
const resultsSection = document.getElementById("results-section");
const btnNew = document.getElementById("btn-new");

// Comparison elements
const comparisonCard = document.getElementById("comparison-card");
const comparisonTabs = document.getElementById("comparison-tabs");
const comparisonOriginalImg = document.getElementById("comparison-original-img");
const comparisonCode = document.getElementById("comparison-code");
const comparisonFontLabel = document.getElementById("comparison-font-label");
const comparisonFontSize = document.getElementById("comparison-font-size");
const comparisonSizeValue = document.getElementById("comparison-size-value");

let selectedFile = null;
let originalDataURL = null; // full image data URL or external URL in URL-analysis mode
let urlAnalysisMode = false; // true when analysis was triggered via URL (no local file)

// ==================
// Crop State
// ==================
let cropRect = null; // { x, y, w, h } in natural image coords
let isDragging = false;
let dragStart = { x: 0, y: 0 };

// ==================
// Theme Toggle
// ==================
(function initTheme() {
  const toggle = document.querySelector("[data-theme-toggle]");
  const root = document.documentElement;
  let theme = "dark";
  root.setAttribute("data-theme", theme);

  toggle.addEventListener("click", () => {
    theme = theme === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", theme);
    toggle.setAttribute("aria-label", `Switch to ${theme === "dark" ? "light" : "dark"} mode`);
    toggle.innerHTML = theme === "dark"
      ? '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>'
      : '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>';
  });
})();

// ==================
// File Upload
// ==================

// <label for="file-input"> handles click natively — no programmatic .click() needed.
// This ensures mobile Safari opens the file dialog reliably.
uploadZone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    fileInput.click();
  }
});

// Detect touch device and adapt upload text
(function adaptUploadText() {
  const isTouchDevice = ("ontouchstart" in window) || (navigator.maxTouchPoints > 0);
  const uploadText = document.getElementById("upload-text");
  if (isTouchDevice && uploadText) {
    uploadText.innerHTML = 'Toque para selecionar uma imagem';
  }
})();

// Drag and drop
uploadZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  uploadZone.classList.add("dragover");
});

uploadZone.addEventListener("dragleave", () => {
  uploadZone.classList.remove("dragover");
});

uploadZone.addEventListener("drop", (e) => {
  e.preventDefault();
  uploadZone.classList.remove("dragover");
  const files = e.dataTransfer.files;
  if (files.length > 0) handleFile(files[0]);
});

fileInput.addEventListener("change", () => {
  if (fileInput.files.length > 0) handleFile(fileInput.files[0]);
});

// ==================
// Import by URL
// ==================

const urlInput = document.getElementById("url-input");
const urlSubmitBtn = document.getElementById("url-submit-btn");
const urlError = document.getElementById("url-error");
const urlInputRow = document.getElementById("url-input-row");
const uploadDivider = document.getElementById("upload-divider");

urlInput.addEventListener("input", () => {
  const val = urlInput.value.trim();
  urlSubmitBtn.disabled = !val || !val.match(/^https?:\/\/.+/i);
  urlError.hidden = true;
});

urlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !urlSubmitBtn.disabled) {
    e.preventDefault();
    fetchImageFromURL();
  }
});

urlSubmitBtn.addEventListener("click", () => {
  fetchImageFromURL();
});

async function fetchImageFromURL() {
  const url = urlInput.value.trim();
  if (!url) return;

  urlError.hidden = true;
  urlSubmitBtn.disabled = true;
  urlSubmitBtn.classList.add("loading");

  // URL flow: send directly to Claude Vision — no download, no preview, no crop.
  // Go straight to loading state, then results.
  uploadSection.hidden = true;
  loadingSection.hidden = false;
  resultsSection.hidden = true;

  try {
    const res = await fetch(`${API}/api/identify-url`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Erro ao analisar imagem." }));
      throw new Error(err.detail || `Erro ${res.status}`);
    }

    const data = await res.json();

    // Store the URL as the original image source for the comparison panel
    originalDataURL = url;
    urlAnalysisMode = true;

    displayResults(data);
  } catch (err) {
    // Go back to upload screen and show error
    uploadSection.hidden = false;
    loadingSection.hidden = true;
    urlError.textContent = err.message;
    urlError.hidden = false;
  } finally {
    urlSubmitBtn.disabled = false;
    urlSubmitBtn.classList.remove("loading");
  }
}

// ==================
// Clipboard Paste (Ctrl+V)
// ==================

document.addEventListener("paste", (e) => {
  // Only handle paste when upload section is visible (no image loaded yet or on upload screen)
  if (uploadSection.hidden) return;

  const items = e.clipboardData?.items;
  if (!items) return;

  for (const item of items) {
    if (item.type.startsWith("image/")) {
      e.preventDefault();
      const file = item.getAsFile();
      if (file) handleFile(file);
      return;
    }
  }
});

function handleFile(file) {
  const allowedTypes = ["image/jpeg", "image/png", "image/gif", "image/webp"];
  if (!allowedTypes.includes(file.type)) {
    alert("Tipo de arquivo não suportado. Use JPEG, PNG, GIF ou WebP.");
    return;
  }
  if (file.size > 20 * 1024 * 1024) {
    alert("Arquivo muito grande. Máximo 20MB.");
    return;
  }

  selectedFile = file;
  urlAnalysisMode = false;
  const reader = new FileReader();
  reader.onload = (e) => {
    originalDataURL = e.target.result;
    previewImage.src = originalDataURL;
    previewImage.onload = () => {
      initCropCanvas();
    };
    previewContainer.hidden = false;
    uploadZone.style.display = "none";
    urlInputRow.style.display = "none";
    uploadDivider.style.display = "none";
    btnAnalyze.disabled = false;
  };
  reader.readAsDataURL(file);
}

btnClear.addEventListener("click", clearUpload);

function clearUpload() {
  selectedFile = null;
  originalDataURL = null;
  urlAnalysisMode = false;
  cropRect = null;
  fileInput.value = "";
  previewImage.src = "";
  previewContainer.hidden = true;
  uploadZone.style.display = "flex";
  btnAnalyze.disabled = true;
  btnResetCrop.hidden = true;
  cropHint.hidden = false;
  // Restore URL input bar
  urlInputRow.style.display = "";
  uploadDivider.style.display = "";
  urlInput.value = "";
  urlError.hidden = true;
}

// ==================
// Crop Tool (Canvas Overlay)
// ==================

function initCropCanvas() {
  const img = previewImage;
  cropCanvas.width = img.clientWidth;
  cropCanvas.height = img.clientHeight;
  cropRect = null;
  btnResetCrop.hidden = true;
  cropHint.hidden = false;
  clearCropOverlay();
}

function getCanvasPos(e) {
  const rect = cropCanvas.getBoundingClientRect();
  // Use the parent container since canvas has pointer-events: none
  const cRect = cropContainer.getBoundingClientRect();
  return {
    x: e.clientX - cRect.left,
    y: e.clientY - cRect.top
  };
}

function toNaturalCoords(x, y) {
  const img = previewImage;
  const scaleX = img.naturalWidth / img.clientWidth;
  const scaleY = img.naturalHeight / img.clientHeight;
  return { x: x * scaleX, y: y * scaleY };
}

// Mouse events on the container (since canvas has pointer-events: none)
cropContainer.addEventListener("mousedown", (e) => {
  if (e.button !== 0) return;
  e.preventDefault();
  isDragging = true;
  dragStart = getCanvasPos(e);
});

cropContainer.addEventListener("mousemove", (e) => {
  if (!isDragging) return;
  e.preventDefault();
  const pos = getCanvasPos(e);
  drawCropRect(dragStart.x, dragStart.y, pos.x - dragStart.x, pos.y - dragStart.y);
});

cropContainer.addEventListener("mouseup", (e) => {
  if (!isDragging) return;
  isDragging = false;
  const pos = getCanvasPos(e);

  let x = Math.min(dragStart.x, pos.x);
  let y = Math.min(dragStart.y, pos.y);
  let w = Math.abs(pos.x - dragStart.x);
  let h = Math.abs(pos.y - dragStart.y);

  // Minimum size check (at least 20px in display coords)
  if (w < 20 || h < 20) {
    cropRect = null;
    clearCropOverlay();
    btnResetCrop.hidden = true;
    cropHint.hidden = false;
    return;
  }

  // Clamp to image bounds
  const iw = previewImage.clientWidth;
  const ih = previewImage.clientHeight;
  x = Math.max(0, Math.min(x, iw));
  y = Math.max(0, Math.min(y, ih));
  w = Math.min(w, iw - x);
  h = Math.min(h, ih - y);

  // Convert to natural image coords
  const tl = toNaturalCoords(x, y);
  const br = toNaturalCoords(x + w, y + h);
  cropRect = { x: tl.x, y: tl.y, w: br.x - tl.x, h: br.y - tl.y };
  btnResetCrop.hidden = false;
  cropHint.hidden = true;

  // Final draw
  drawCropRect(Math.min(dragStart.x, pos.x), Math.min(dragStart.y, pos.y), w, h);
});

// Touch support
cropContainer.addEventListener("touchstart", (e) => {
  if (e.touches.length !== 1) return;
  e.preventDefault();
  isDragging = true;
  const touch = e.touches[0];
  dragStart = getCanvasPos(touch);
}, { passive: false });

cropContainer.addEventListener("touchmove", (e) => {
  if (!isDragging || e.touches.length !== 1) return;
  e.preventDefault();
  const touch = e.touches[0];
  const pos = getCanvasPos(touch);
  drawCropRect(dragStart.x, dragStart.y, pos.x - dragStart.x, pos.y - dragStart.y);
}, { passive: false });

cropContainer.addEventListener("touchend", (e) => {
  if (!isDragging) return;
  isDragging = false;
  // Use changedTouches for end position
  const touch = e.changedTouches[0];
  const pos = getCanvasPos(touch);

  let x = Math.min(dragStart.x, pos.x);
  let y = Math.min(dragStart.y, pos.y);
  let w = Math.abs(pos.x - dragStart.x);
  let h = Math.abs(pos.y - dragStart.y);

  if (w < 20 || h < 20) {
    cropRect = null;
    clearCropOverlay();
    btnResetCrop.hidden = true;
    cropHint.hidden = false;
    return;
  }

  const iw = previewImage.clientWidth;
  const ih = previewImage.clientHeight;
  x = Math.max(0, Math.min(x, iw));
  y = Math.max(0, Math.min(y, ih));
  w = Math.min(w, iw - x);
  h = Math.min(h, ih - y);

  const tl = toNaturalCoords(x, y);
  const br = toNaturalCoords(x + w, y + h);
  cropRect = { x: tl.x, y: tl.y, w: br.x - tl.x, h: br.y - tl.y };
  btnResetCrop.hidden = false;
  cropHint.hidden = true;
  drawCropRect(x, y, w, h);
});

function drawCropRect(x, y, w, h) {
  const ctx = cropCanvas.getContext("2d");
  const cw = cropCanvas.width;
  const ch = cropCanvas.height;

  // Normalize if dragged in negative direction
  let rx = x, ry = y, rw = w, rh = h;
  if (rw < 0) { rx += rw; rw = -rw; }
  if (rh < 0) { ry += rh; rh = -rh; }

  ctx.clearRect(0, 0, cw, ch);

  // Semi-transparent dark overlay outside selection
  ctx.fillStyle = "rgba(0, 0, 0, 0.55)";
  ctx.fillRect(0, 0, cw, ch);

  // Clear the selection area (reveal image)
  ctx.clearRect(rx, ry, rw, rh);

  // Draw selection border
  ctx.strokeStyle = "#58a6ff";
  ctx.lineWidth = 2;
  ctx.setLineDash([6, 3]);
  ctx.strokeRect(rx, ry, rw, rh);
  ctx.setLineDash([]);

  // Corner handles
  const hs = 6;
  ctx.fillStyle = "#58a6ff";
  // top-left
  ctx.fillRect(rx - hs/2, ry - hs/2, hs, hs);
  // top-right
  ctx.fillRect(rx + rw - hs/2, ry - hs/2, hs, hs);
  // bottom-left
  ctx.fillRect(rx - hs/2, ry + rh - hs/2, hs, hs);
  // bottom-right
  ctx.fillRect(rx + rw - hs/2, ry + rh - hs/2, hs, hs);
}

function clearCropOverlay() {
  const ctx = cropCanvas.getContext("2d");
  ctx.clearRect(0, 0, cropCanvas.width, cropCanvas.height);
}

btnResetCrop.addEventListener("click", () => {
  cropRect = null;
  clearCropOverlay();
  btnResetCrop.hidden = true;
  cropHint.hidden = false;
});

// ==================
// Crop Image to Blob
// ==================

function getCroppedBlob() {
  return new Promise((resolve) => {
    if (!cropRect || !originalDataURL) {
      // No crop — send entire file
      resolve(selectedFile);
      return;
    }

    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(cropRect.w);
      canvas.height = Math.round(cropRect.h);
      const ctx = canvas.getContext("2d");
      ctx.drawImage(
        img,
        Math.round(cropRect.x), Math.round(cropRect.y),
        Math.round(cropRect.w), Math.round(cropRect.h),
        0, 0,
        Math.round(cropRect.w), Math.round(cropRect.h)
      );
      canvas.toBlob((blob) => {
        resolve(blob);
      }, "image/png");
    };
    img.src = originalDataURL;
  });
}

// ==================
// Analysis
// ==================

btnAnalyze.addEventListener("click", analyzeFont);

async function analyzeFont() {
  if (!selectedFile) return;

  let imageBlob;
  try {
    imageBlob = await getCroppedBlob();
  } catch (err) {
    alert(`Erro ao preparar imagem: ${err.message}`);
    return;
  }

  const quality = await assessCropQuality(imageBlob);
  if (quality.warnings.length > 0) {
    const msg = "A análise pode não acertar porque:\n\n• " +
      quality.warnings.join("\n• ") +
      "\n\nContinuar mesmo assim?";
    if (!confirm(msg)) return;
  }

  // Show loading
  uploadSection.hidden = true;
  loadingSection.hidden = false;
  resultsSection.hidden = true;

  try {
    const formData = new FormData();
    formData.append("file", imageBlob, "image.png");

    const res = await fetch(`${API}/api/identify`, {
      method: "POST",
      body: formData,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Analysis failed" }));
      throw new Error(err.detail || "Analysis failed");
    }

    const data = await res.json();
    displayResults(data);
  } catch (err) {
    alert(`Erro na análise: ${err.message}`);
    // Go back to upload
    uploadSection.hidden = false;
    loadingSection.hidden = true;
  }
}

// ==================
// Crop Quality Assessment
// ==================

// Avalia o blob que vai ser enviado e retorna { warnings: string[], metrics }.
// Rodamos rápido: decodifica via ImageBitmap, mede dimensões, contraste (stddev
// de luminância) e densidade de borda para estimar se dá para identificar fonte.
async function assessCropQuality(blob) {
  const out = { warnings: [], metrics: {} };
  if (!blob) return out;

  let bitmap;
  try {
    bitmap = await createImageBitmap(blob);
  } catch {
    return out; // falha silenciosa — deixa o backend validar
  }

  const w = bitmap.width, h = bitmap.height;
  out.metrics.width = w;
  out.metrics.height = h;

  if (w < 300 || h < 80) {
    out.warnings.push(`recorte muito pequeno (${w}x${h}px) — fontes parecidas ficam indistinguíveis`);
  }

  // Mini canvas para medir contraste + densidade de borda (amostragem até 600x400)
  const targetW = Math.min(w, 600);
  const targetH = Math.round(h * (targetW / w));
  const canvas = document.createElement("canvas");
  canvas.width = targetW;
  canvas.height = targetH;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(bitmap, 0, 0, targetW, targetH);
  bitmap.close?.();

  const { data } = ctx.getImageData(0, 0, targetW, targetH);
  let sum = 0, sumSq = 0, n = 0;
  const lum = new Uint8ClampedArray(targetW * targetH);
  for (let i = 0, j = 0; i < data.length; i += 4, j++) {
    // Rec. 709 luma
    const y = (0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2]) | 0;
    lum[j] = y;
    sum += y;
    sumSq += y * y;
    n++;
  }
  const mean = sum / n;
  const variance = sumSq / n - mean * mean;
  const stddev = Math.sqrt(Math.max(0, variance));
  out.metrics.contrast = +(stddev / 255).toFixed(3);
  out.metrics.meanLuminance = +(mean / 255).toFixed(3);

  if (out.metrics.contrast < 0.12) {
    out.warnings.push("contraste baixo — o texto está muito próximo do fundo em luminosidade");
  }

  // Densidade de borda rápida: diferença horizontal absoluta média
  let edgeSum = 0, edgeN = 0;
  for (let y = 0; y < targetH; y++) {
    for (let x = 1; x < targetW; x++) {
      edgeSum += Math.abs(lum[y * targetW + x] - lum[y * targetW + x - 1]);
      edgeN++;
    }
  }
  const edgeDensity = edgeSum / edgeN / 255;
  out.metrics.edgeDensity = +edgeDensity.toFixed(3);
  if (edgeDensity < 0.02) {
    out.warnings.push("pouco conteúdo de texto — tente incluir mais linhas de código no recorte");
  }

  return out;
}

// ==================
// Display Results
// ==================

// Track comparison state
let comparisonFonts = []; // [{name, confidence, loaded}]
let activeTabIndex = 0;
let extractedCode = "";

function displayResults(data) {
  loadingSection.hidden = true;
  resultsSection.hidden = false;

  // Store for feedback reference & reset feedback UI
  lastAnalysisData = data;
  resetFeedbackUI();

  const primary = data.primary_match || {};
  const alternatives = data.alternatives || [];
  const features = data.observed_features || {};
  const notes = data.notes || "";
  extractedCode = data.extracted_code || "";

  // Primary card
  document.getElementById("primary-name").textContent = primary.name || "Unknown";

  const conf = Math.round((primary.confidence || 0) * 100);
  const confBadge = document.getElementById("primary-confidence");
  confBadge.querySelector(".confidence-value").textContent = `${conf}%`;
  // Thresholds recalibrados agora que confidence mistura visual + upstream (0.7*visual + 0.3*upstream)
  confBadge.className = "confidence-badge " + (conf >= 75 ? "high" : conf >= 55 ? "medium" : "low");

  // Visual similarity (novo): só aparece se o backend devolveu
  const visSimEl = document.getElementById("primary-visual-sim");
  if (visSimEl) {
    if (typeof primary.visual_similarity === "number") {
      const vs = Math.round(primary.visual_similarity * 100);
      visSimEl.hidden = false;
      visSimEl.querySelector(".vs-value").textContent = `${vs}%`;
      visSimEl.querySelector(".vs-bar-fill").style.width = `${vs}%`;
      visSimEl.classList.remove("vs-low", "vs-medium", "vs-high");
      visSimEl.classList.add(vs >= 75 ? "vs-high" : vs >= 55 ? "vs-medium" : "vs-low");
    } else if (primary.renderable === false) {
      visSimEl.hidden = false;
      visSimEl.querySelector(".vs-value").textContent = "—";
      visSimEl.querySelector(".vs-bar-fill").style.width = "0%";
      visSimEl.classList.remove("vs-low", "vs-medium", "vs-high");
      visSimEl.classList.add("vs-unavailable");
      visSimEl.title = "Fonte paga/restrita — não foi possível verificar visualmente";
    } else {
      visSimEl.hidden = true;
    }
  }

  // CTA de baixa similaridade: sugere melhor recorte
  const lowSimEl = document.getElementById("low-sim-cta");
  if (lowSimEl) {
    const sim = typeof primary.visual_similarity === "number" ? primary.visual_similarity : null;
    lowSimEl.hidden = !(sim !== null && sim < 0.55);
  }

  document.getElementById("primary-reasoning").textContent = primary.reasoning || "";

  // Features tags
  const featuresEl = document.getElementById("primary-features");
  featuresEl.innerHTML = "";
  (primary.distinguishing_features || []).forEach(f => {
    const tag = document.createElement("span");
    tag.className = "feature-tag";
    tag.textContent = f;
    featuresEl.appendChild(tag);
  });

  // Meta
  const metaEl = document.getElementById("primary-meta");
  metaEl.innerHTML = "";
  if (primary.license) {
    metaEl.innerHTML += `<span class="meta-item">Licença: ${esc(primary.license)}</span>`;
  }
  if (primary.is_free !== null && primary.is_free !== undefined) {
    const cls = primary.is_free ? "free" : "paid";
    const label = primary.is_free ? "Gratuita" : "Paga";
    const priceStr = (!primary.is_free && primary.price_hint) ? ` · ~${esc(primary.price_hint)}` : "";
    metaEl.innerHTML += `<span class="meta-item ${cls}">${label}${priceStr}</span>`;
  }

  // Actions
  const actionsEl = document.getElementById("primary-actions");
  actionsEl.innerHTML = "";
  if (primary.is_free === false && primary.homepage) {
    // Paid font — show prominent "Comprar" button
    actionsEl.innerHTML += `<a href="${esc(primary.homepage)}" target="_blank" rel="noopener" class="btn-link primary">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>
      Comprar
    </a>`;
  } else if (primary.download_url) {
    actionsEl.innerHTML += `<a href="${esc(primary.download_url)}" target="_blank" rel="noopener" class="btn-link primary">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
      Download
    </a>`;
  }
  if (primary.homepage) {
    actionsEl.innerHTML += `<a href="${esc(primary.homepage)}" target="_blank" rel="noopener" class="btn-link">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
      Homepage
    </a>`;
  }
  if (primary.download_url && primary.is_free !== false) {
    // Only show separate download if not already shown as primary action
  } else if (primary.download_url && primary.is_free === false) {
    actionsEl.innerHTML += `<a href="${esc(primary.download_url)}" target="_blank" rel="noopener" class="btn-link">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
      Download
    </a>`;
  }
  if (primary.name && primary.name !== "Unknown") {
    const searchQuery = encodeURIComponent(primary.name + " font download");
    actionsEl.innerHTML += `<a href="https://www.google.com/search?q=${searchQuery}" target="_blank" rel="noopener" class="btn-link">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      Buscar
    </a>`;
  }

  // Observed features
  const featuresGrid = document.getElementById("features-grid");
  featuresGrid.innerHTML = "";

  const featureLabels = {
    has_ligatures: { label: "Ligaduras", format: v => v ? "Sim" : "Não" },
    zero_style: { label: "Estilo do Zero", format: v => v },
    a_style: { label: "Estilo do 'a'", format: v => v },
    g_style: { label: "Estilo do 'g'", format: v => v },
    l_serif: { label: "Serifa no 'l'", format: v => v ? "Sim" : "Não" },
    asterisk_position: { label: "Posição do *", format: v => v },
    overall_weight: { label: "Peso", format: v => v },
    approximate_style: { label: "Estilo", format: v => v },
  };

  for (const [key, config] of Object.entries(featureLabels)) {
    if (features[key] !== undefined && features[key] !== null && features[key] !== "unknown") {
      const item = document.createElement("div");
      item.className = "feature-item";
      item.innerHTML = `
        <span class="feature-label">${config.label}</span>
        <span class="feature-value">${esc(String(config.format(features[key])))}</span>
      `;
      featuresGrid.appendChild(item);
    }
  }

  // Notes
  const notesEl = document.getElementById("features-notes");
  if (notes) {
    notesEl.textContent = notes;
    notesEl.hidden = false;
  } else {
    notesEl.hidden = true;
  }

  // Alternatives
  const altCard = document.getElementById("alternatives-card");
  const altList = document.getElementById("alternatives-list");
  altList.innerHTML = "";

  if (alternatives.length > 0) {
    altCard.hidden = false;
    alternatives.forEach(alt => {
      const altConf = Math.round((alt.confidence || 0) * 100);
      const item = document.createElement("div");
      item.className = "alt-item";

      // Price badge
      let priceBadge = "";
      if (alt.is_free === false) {
        const priceStr = alt.price_hint ? ` · ~${esc(alt.price_hint)}` : "";
        priceBadge = `<span class="alt-price-badge paid">Paga${priceStr}</span>`;
      } else if (alt.is_free === true) {
        priceBadge = `<span class="alt-price-badge free">Gratuita</span>`;
      }

      let linksHtml = "";
      if (alt.is_free === false && alt.homepage) {
        linksHtml += `<a href="${esc(alt.homepage)}" target="_blank" rel="noopener" class="btn-link">Comprar</a>`;
      } else if (alt.download_url) {
        linksHtml += `<a href="${esc(alt.download_url)}" target="_blank" rel="noopener" class="btn-link">Download</a>`;
      }
      if (alt.homepage) {
        linksHtml += `<a href="${esc(alt.homepage)}" target="_blank" rel="noopener" class="btn-link">Homepage</a>`;
      }
      if (alt.name) {
        const q = encodeURIComponent(alt.name + " font download");
        linksHtml += `<a href="https://www.google.com/search?q=${q}" target="_blank" rel="noopener" class="btn-link">Buscar</a>`;
      }

      const vs = typeof alt.visual_similarity === "number" ? Math.round(alt.visual_similarity * 100) : null;
      const vsBadge = vs !== null
        ? `<span class="alt-visual-sim ${vs >= 75 ? "vs-high" : vs >= 55 ? "vs-medium" : "vs-low"}" title="Similaridade visual com a imagem original">${vs}% visual</span>`
        : (alt.renderable === false
            ? `<span class="alt-visual-sim vs-unavailable" title="Fonte paga/restrita — não verificável visualmente">não verificável</span>`
            : "");

      item.innerHTML = `
        <div class="alt-header">
          <span class="alt-name">${esc(alt.name || "?")}${priceBadge ? " " + priceBadge : ""}</span>
          <span class="alt-confidence">${altConf}%</span>
        </div>
        ${vsBadge ? `<div class="alt-metrics">${vsBadge}</div>` : ""}
        <p class="alt-reasoning">${esc(alt.reasoning || "")}</p>
        ${linksHtml ? `<div class="alt-links">${linksHtml}</div>` : ""}
      `;
      altList.appendChild(item);
    });
  } else {
    altCard.hidden = true;
  }

  // ==================
  // Visual Comparison Panel
  // ==================
  setupComparison(primary, alternatives);
}

// ==================
// Comparison Panel Logic
// ==================

async function setupComparison(primary, alternatives) {
  // Set original image for comparison panel
  if (urlAnalysisMode && originalDataURL) {
    // URL mode: use the external URL directly as the image source
    comparisonOriginalImg.src = originalDataURL;
  } else if (cropRect && originalDataURL) {
    // File mode with crop: show cropped region as original
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = Math.round(cropRect.w);
      c.height = Math.round(cropRect.h);
      const ctx = c.getContext("2d");
      ctx.drawImage(img,
        Math.round(cropRect.x), Math.round(cropRect.y),
        Math.round(cropRect.w), Math.round(cropRect.h),
        0, 0, Math.round(cropRect.w), Math.round(cropRect.h)
      );
      comparisonOriginalImg.src = c.toDataURL("image/png");
    };
    img.src = originalDataURL;
  } else if (originalDataURL) {
    comparisonOriginalImg.src = originalDataURL;
  }

  // Build font list for tabs: primary + alternatives
  comparisonFonts = [];
  if (primary.name && primary.name !== "Unknown") {
    comparisonFonts.push({
      name: primary.name,
      confidence: Math.round((primary.confidence || 0) * 100),
      loaded: false,
    });
  }
  (alternatives || []).forEach(alt => {
    if (alt.name) {
      comparisonFonts.push({
        name: alt.name,
        confidence: Math.round((alt.confidence || 0) * 100),
        loaded: false,
      });
    }
  });

  if (comparisonFonts.length === 0 || !extractedCode) {
    comparisonCard.hidden = true;
    return;
  }

  comparisonCard.hidden = false;

  // Build tabs
  comparisonTabs.innerHTML = "";
  comparisonFonts.forEach((font, i) => {
    const btn = document.createElement("button");
    btn.className = "comparison-tab" + (i === 0 ? " active" : "");
    btn.innerHTML = `${esc(font.name)} <span class="tab-confidence">${font.confidence}%</span>`;
    btn.addEventListener("click", () => switchComparisonTab(i));
    comparisonTabs.appendChild(btn);
  });

  // Set code
  comparisonCode.textContent = extractedCode;

  // Font size slider
  const currentSize = parseInt(comparisonFontSize.value, 10);
  comparisonCode.style.fontSize = currentSize + "px";
  comparisonSizeValue.textContent = currentSize + "px";

  comparisonFontSize.oninput = () => {
    const sz = comparisonFontSize.value;
    comparisonCode.style.fontSize = sz + "px";
    comparisonSizeValue.textContent = sz + "px";
  };

  // Load and switch to first font
  activeTabIndex = 0;
  await switchComparisonTab(0);
}

async function switchComparisonTab(index) {
  activeTabIndex = index;
  const font = comparisonFonts[index];

  // Update tabs
  const tabs = comparisonTabs.querySelectorAll(".comparison-tab");
  tabs.forEach((t, i) => t.classList.toggle("active", i === index));

  // Update label
  comparisonFontLabel.textContent = font.name;

  // Load font if needed
  if (!font.loaded) {
    font.loaded = await tryLoadGoogleFont(font.name);
  }

  // Apply font
  if (font.loaded) {
    comparisonCode.style.fontFamily = `'${font.name}', monospace`;
  } else {
    comparisonCode.style.fontFamily = "monospace";
    comparisonFontLabel.textContent = font.name + " (não disponível no Google Fonts)";
  }
}

// ==================
// Font Loading
// ==================

const loadedFonts = new Set();

async function tryLoadGoogleFont(fontName) {
  if (loadedFonts.has(fontName)) return true;

  const encodedName = encodeURIComponent(fontName);
  const url = `https://fonts.googleapis.com/css2?family=${encodedName.replace(/%20/g, "+")}:wght@400;700&display=swap`;

  try {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = url;
    document.head.appendChild(link);

    return new Promise(resolve => {
      let attempts = 0;
      const check = () => {
        if (document.fonts.check(`16px "${fontName}"`)) {
          loadedFonts.add(fontName);
          resolve(true);
        } else if (attempts++ > 25) {
          resolve(false);
        } else {
          setTimeout(check, 200);
        }
      };
      setTimeout(check, 300);
    });
  } catch {
    return false;
  }
}

// ==================
// New Analysis
// ==================

btnNew.addEventListener("click", () => {
  resultsSection.hidden = true;
  uploadSection.hidden = false;
  clearUpload();
});

// ==================
// Feedback System
// ==================

const feedbackCard = document.getElementById("feedback-card");
const feedbackReasons = document.getElementById("feedback-reasons");
const feedbackForm = document.getElementById("feedback-form");
const feedbackDetails = document.getElementById("feedback-details");
const feedbackCancel = document.getElementById("feedback-cancel");
const feedbackSubmit = document.getElementById("feedback-submit");
const feedbackSuccess = document.getElementById("feedback-success");
const feedbackRetry = document.getElementById("feedback-retry");

let selectedReason = null;
let lastAnalysisData = null; // Store last analysis for feedback context

// lastAnalysisData is set inside displayResults()

// Reason button click
feedbackReasons.addEventListener("click", (e) => {
  const btn = e.target.closest(".feedback-reason-btn");
  if (!btn) return;

  // Toggle selected state
  feedbackReasons.querySelectorAll(".feedback-reason-btn").forEach(b => b.classList.remove("selected"));
  btn.classList.add("selected");
  selectedReason = btn.dataset.reason;

  // Show expanded form
  feedbackForm.hidden = false;
  feedbackDetails.focus();
});

// Cancel
feedbackCancel.addEventListener("click", () => {
  resetFeedbackUI();
});

// Submit
feedbackSubmit.addEventListener("click", async () => {
  if (!selectedReason) return;

  feedbackSubmit.disabled = true;
  feedbackSubmit.textContent = "Enviando...";

  const payload = {
    primary_font: lastAnalysisData?.primary_match?.name || "Unknown",
    reason: selectedReason,
    details: feedbackDetails.value.trim() || null,
    suggested_fonts: [
      lastAnalysisData?.primary_match?.name,
      ...(lastAnalysisData?.alternatives || []).map(a => a.name)
    ].filter(Boolean),
    timestamp: new Date().toISOString(),
  };

  try {
    const res = await fetch(`${API}/api/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) throw new Error("Falha no envio");

    // Show success state
    feedbackReasons.hidden = true;
    feedbackForm.hidden = true;
    feedbackSuccess.hidden = false;
  } catch (err) {
    alert(`Erro ao enviar feedback: ${err.message}`);
  } finally {
    feedbackSubmit.disabled = false;
    feedbackSubmit.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Enviar feedback`;
  }
});

// Retry from feedback
feedbackRetry.addEventListener("click", () => {
  resultsSection.hidden = true;
  uploadSection.hidden = false;
  clearUpload();
});

function resetFeedbackUI() {
  selectedReason = null;
  feedbackReasons.querySelectorAll(".feedback-reason-btn").forEach(b => b.classList.remove("selected"));
  feedbackForm.hidden = true;
  feedbackSuccess.hidden = true;
  feedbackReasons.hidden = false;
  feedbackDetails.value = "";
}

// ==================
// Utilities
// ==================

function esc(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
