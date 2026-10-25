let mode = "login";

fetch("/api/auth/status").then((response) => response.json()).then((status) => {
  if (!status.registration_enabled) {
    document.querySelector('[data-mode="register"]').hidden = true;
  }
});

document.querySelectorAll(".auth-tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    mode = button.dataset.mode;
    document.querySelectorAll(".auth-tabs button").forEach((item) => item.classList.toggle("active", item === button));
    const registering = mode === "register";
    document.querySelector("#organization-field").hidden = !registering;
    document.querySelector("#auth-organization").required = registering;
    document.querySelector("#auth-title").textContent = registering ? "Crea il tuo workspace" : "Bentornato";
    document.querySelector("#auth-eyebrow").textContent = registering ? "NUOVO ACCOUNT" : "AREA RISERVATA";
    document.querySelector("#auth-submit").textContent = registering ? "Crea account →" : "Accedi →";
    document.querySelector("#auth-password").autocomplete = registering ? "new-password" : "current-password";
    document.querySelector("#auth-error").textContent = "";
  });
});

document.querySelector("#auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = document.querySelector("#auth-submit");
  const error = document.querySelector("#auth-error");
  submit.disabled = true;
  error.textContent = "";
  const response = await fetch(`/api/auth/${mode}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: document.querySelector("#auth-email").value,
      password: document.querySelector("#auth-password").value,
      organization_name: document.querySelector("#auth-organization").value,
    }),
  });
  const result = await response.json();
  if (response.ok) {
    window.location.href = "/app";
    return;
  }
  error.textContent = result.detail || "Operazione non riuscita";
  submit.disabled = false;
});
