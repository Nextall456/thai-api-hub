// Thai API Hub — client interactions
(function () {
  // คัดลอกโค้ด/คีย์
  document.addEventListener("click", function (e) {
    const btn = e.target.closest("[data-copy],[data-copy-target]");
    if (!btn) return;
    let text = "";
    if (btn.dataset.copyTarget) {
      const el = document.getElementById(btn.dataset.copyTarget);
      text = el ? el.textContent : "";
    } else {
      const box = btn.closest(".code-box");
      if (box) {
        const activePane = box.querySelector(".code-pane.active pre");
        text = activePane ? activePane.textContent : "";
      } else {
        const code = btn.closest(".card, .code")?.querySelector("pre");
        text = code ? code.textContent : "";
      }
    }
    if (text) {
      navigator.clipboard.writeText(text.trim()).then(() => {
        const old = btn.textContent;
        btn.textContent = "✓ คัดลอกแล้ว";
        setTimeout(() => (btn.textContent = old), 1600);
      });
    }
  });

  // สลับแท็บโค้ดในหน้าแรก (cURL, Python, TS, Go)
  document.addEventListener("click", function (e) {
    const tab = e.target.closest(".code-tab");
    if (!tab) return;
    const target = tab.dataset.lang;
    const container = tab.closest(".code-box");
    if (!container) return;
    container.querySelectorAll(".code-tab").forEach(t => t.classList.remove("active"));
    container.querySelectorAll(".code-pane").forEach(p => p.classList.remove("active"));
    tab.classList.add("active");
    const pane = container.querySelector(`.code-pane[data-lang="${target}"]`);
    if (pane) pane.classList.add("active");
  });


  // ห้องทดลอง AI
  const send = document.getElementById("pg-send");
  if (send) {
    const out = document.getElementById("pg-output");
    const meta = document.getElementById("pg-meta");
    const status = document.getElementById("pg-status");
    send.addEventListener("click", async function () {
      const prompt = document.getElementById("pg-prompt").value.trim();
      const model = document.getElementById("pg-model").value;
      if (!prompt) { status.textContent = "กรอกข้อความก่อนนะ"; return; }
      send.disabled = true;
      out.classList.add("busy");
      out.textContent = "กำลังประมวลผล… (ครั้งแรกอาจช้าหน่อยเพราะโหลดโมเดลในเครื่อง)";
      status.textContent = "";
      meta.textContent = "";
      try {
        const r = await fetch("/dashboard/playground", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt: prompt, model: model }),
        });
        const j = await r.json();
        if (!r.ok) {
          out.textContent = "เกิดข้อผิดพลาด";
          status.textContent = j.error || ("HTTP " + r.status);
        } else {
          out.textContent = j.content || "(ว่างเปล่า)";
          out.classList.remove("muted");
          meta.textContent = "🧠 backend: " + j.backend + " · ⏱ " + j.latency_ms + " ms · 🎟 " + j.tokens + " tokens";
        }
      } catch (err) {
        out.textContent = "เชื่อมต่อไม่สำเร็จ: " + err;
      } finally {
        send.disabled = false;
        out.classList.remove("busy");
      }
    });
  }
})();
