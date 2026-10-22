// Progressive enhancement: navigation, disclosures, and code work without JS.
const menu = document.querySelector(".mobile-menu");
if (menu) {
  menu.querySelectorAll('a[href^="#"]').forEach((link) => {
    link.addEventListener("click", () => { menu.open = false; });
  });
  menu.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && menu.open) {
      menu.open = false;
      menu.querySelector("summary").focus();
    }
  });
}

document.querySelectorAll("[data-copy]").forEach((button) => {
  const source = document.getElementById(button.dataset.copy);
  const status = button.parentElement.querySelector(".copy-status");
  if (!source || !status) return;
  button.hidden = false;

  button.addEventListener("click", async () => {
    status.textContent = "";
    try {
      await navigator.clipboard.writeText(source.textContent.trim());
      status.textContent = "Copied.";
    } catch {
      // Clipboard permissions and insecure contexts can block copying.
      // Keep the content available and select it for manual copying.
      const selection = window.getSelection();
      if (selection) {
        const range = document.createRange();
        range.selectNodeContents(source);
        selection.removeAllRanges();
        selection.addRange(range);
        status.textContent = "Selected. Copy with your keyboard.";
      } else {
        status.textContent = "Select and copy the text below.";
      }
    }
  });
});
