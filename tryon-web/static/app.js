(() => {
  const MAX_REFS = 3;

  const beforeInput = document.getElementById("before-file");
  const beforePreviewWrap = document.getElementById("before-preview-wrap");
  const beforePreview = document.getElementById("before-preview");
  const btnClearBefore = document.getElementById("btn-clear-before");
  const btnCamera = document.getElementById("btn-camera");
  const cameraBox = document.getElementById("camera-box");
  const video = document.getElementById("camera-video");
  const canvas = document.getElementById("camera-canvas");
  const btnSnap = document.getElementById("btn-snap");
  const btnCancelCamera = document.getElementById("btn-cancel-camera");

  const refInput = document.getElementById("ref-file");
  const refsGrid = document.getElementById("refs-grid");
  const refsHint = document.getElementById("refs-hint");

  const btnRun = document.getElementById("btn-run");
  const progress = document.getElementById("progress");
  const progressText = document.getElementById("progress-text");
  const errorEl = document.getElementById("error");
  const stepAfter = document.getElementById("step-after");
  const compare = document.getElementById("compare");
  const afterLead = document.getElementById("after-lead");

  let beforeFile = null;
  let refFiles = [];
  let stream = null;

  function sync() {
    btnRun.disabled = !(beforeFile && refFiles.length > 0);
    refsHint.textContent = `Загружено: ${refFiles.length} из ${MAX_REFS}`;
  }

  function showError(msg) {
    errorEl.textContent = msg || "";
    errorEl.classList.toggle("hidden", !msg);
  }

  function setBefore(file) {
    beforeFile = file;
    beforePreview.src = URL.createObjectURL(file);
    beforePreviewWrap.classList.remove("hidden");
    btnClearBefore.classList.remove("hidden");
    sync();
  }

  function clearBefore() {
    beforeFile = null;
    beforePreview.removeAttribute("src");
    beforePreviewWrap.classList.add("hidden");
    btnClearBefore.classList.add("hidden");
    sync();
  }

  function renderRefs() {
    refsGrid.innerHTML = "";
    refFiles.forEach((file, idx) => {
      const card = document.createElement("div");
      card.className = "ref-card";
      const img = document.createElement("img");
      img.alt = `Референс ${idx + 1}`;
      img.src = URL.createObjectURL(file);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "remove";
      remove.setAttribute("aria-label", "Удалить");
      remove.textContent = "×";
      remove.addEventListener("click", () => {
        refFiles.splice(idx, 1);
        renderRefs();
        sync();
      });
      card.append(img, remove);
      refsGrid.appendChild(card);
    });
  }

  async function stopCamera() {
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
    cameraBox.classList.add("hidden");
    video.srcObject = null;
  }

  beforeInput.addEventListener("change", () => {
    const file = beforeInput.files && beforeInput.files[0];
    if (file) setBefore(file);
    beforeInput.value = "";
  });

  btnClearBefore.addEventListener("click", clearBefore);

  btnCamera.addEventListener("click", async () => {
    showError("");
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user" },
        audio: false,
      });
      video.srcObject = stream;
      cameraBox.classList.remove("hidden");
    } catch (err) {
      showError("Не удалось открыть камеру. Разрешите доступ или загрузите файл.");
    }
  });

  btnCancelCamera.addEventListener("click", stopCamera);

  btnSnap.addEventListener("click", async () => {
    const w = video.videoWidth || 720;
    const h = video.videoHeight || 960;
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, w, h);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
    if (!blob) {
      showError("Не удалось сделать снимок");
      return;
    }
    setBefore(new File([blob], `selfie_${Date.now()}.jpg`, { type: "image/jpeg" }));
    await stopCamera();
  });

  refInput.addEventListener("change", () => {
    const files = Array.from(refInput.files || []);
    refInput.value = "";
    for (const file of files) {
      if (refFiles.length >= MAX_REFS) break;
      refFiles.push(file);
    }
    if (files.length && refFiles.length >= MAX_REFS && files.length > MAX_REFS - (refFiles.length - files.length)) {
      // soft notice only via hint
    }
    renderRefs();
    sync();
  });

  btnRun.addEventListener("click", async () => {
    showError("");
    if (!beforeFile || !refFiles.length) return;

    btnRun.disabled = true;
    progress.classList.remove("hidden");
    progressText.textContent = `Отправляем ${refFiles.length} референс(а) в YouCam…`;
    stepAfter.classList.add("hidden");
    compare.innerHTML = "";

    const form = new FormData();
    form.append("before", beforeFile, beforeFile.name);
    refFiles.forEach((f, i) => form.append("refs", f, f.name || `ref_${i + 1}.jpg`));

    try {
      const resp = await fetch("/api/tryon", { method: "POST", body: form });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(data.detail || data.error || `Ошибка сервера (${resp.status})`);
      }

      afterLead.textContent = `Получено вариантов: ${(data.results || []).filter((r) => r.status === "ok").length} из ${refFiles.length}`;
      compare.innerHTML = "";

      const beforeCard = document.createElement("article");
      beforeCard.className = "result-card";
      beforeCard.innerHTML = `<img src="${data.before_url}" alt="До" /><div class="label">До</div>`;
      compare.appendChild(beforeCard);

      (data.results || []).forEach((item) => {
        const card = document.createElement("article");
        if (item.status === "ok") {
          card.className = "result-card";
          card.innerHTML = `<img src="${item.result_url}" alt="После ${item.index}" /><div class="label">После · референс ${item.index}</div>`;
        } else {
          card.className = "result-card error";
          card.textContent = `Референс ${item.index}: ${item.error || "ошибка"}`;
        }
        compare.appendChild(card);
      });

      stepAfter.classList.remove("hidden");
      stepAfter.scrollIntoView({ behavior: "smooth", block: "start" });
      progressText.textContent = "Готово";
    } catch (err) {
      showError(err.message || String(err));
      progressText.textContent = "Не удалось выполнить примерку";
    } finally {
      progress.classList.add("hidden");
      sync();
    }
  });

  sync();
})();
