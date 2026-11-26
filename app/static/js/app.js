document.addEventListener("click", (event) => {
  const confirmButton = event.target.closest("[data-confirm]");
  if (confirmButton && !window.confirm(confirmButton.getAttribute("data-confirm"))) {
    event.preventDefault();
    return;
  }

  const shot = event.target.closest("[data-full]");
  if (shot) {
    event.preventDefault();
    const box = document.getElementById("lightbox");
    const image = box.querySelector("img");
    image.src = shot.getAttribute("data-full");
    image.alt = shot.querySelector("img")?.alt || "截圖";
    box.hidden = false;
    return;
  }

  if (event.target.closest("[data-close-lightbox]") || event.target.id === "lightbox") {
    const box = document.getElementById("lightbox");
    box.hidden = true;
    box.querySelector("img").removeAttribute("src");
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    const box = document.getElementById("lightbox");
    if (box && !box.hidden) {
      box.hidden = true;
      box.querySelector("img").removeAttribute("src");
    }
  }
});

document.addEventListener("change", (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || input.type !== "file") return;
  const label = input.closest("form")?.querySelector(".file-name");
  if (!label) return;
  const names = [...input.files].map((file) => file.name);
  label.textContent = names.length ? names.join("、") : "未選擇檔案";
});

const clientFilter = document.getElementById("client-filter");
if (clientFilter) {
  clientFilter.addEventListener("input", () => {
    const query = clientFilter.value.trim().toLowerCase();
    document.querySelectorAll("tr[data-client]").forEach((row) => {
      const haystack = `${row.dataset.client} ${row.dataset.site}`.toLowerCase();
      row.hidden = Boolean(query) && !haystack.includes(query);
    });
  });
}

document.querySelectorAll("[data-issue-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    const mode = button.dataset.issueFilter;
    document.querySelectorAll("[data-issue-filter]").forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    document.querySelectorAll("[data-issue-status]").forEach((row) => {
      const status = row.dataset.issueStatus;
      const open = status === "開放" || status === "跟進中";
      const visible = mode === "all" || (mode === "open" && open) || (mode === "closed" && status === "已關閉");
      row.hidden = !visible;
    });
  });
});
