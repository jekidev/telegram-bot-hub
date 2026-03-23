const botGrid = document.getElementById("bot-grid");
const template = document.getElementById("bot-card-template");
const refreshButton = document.getElementById("refresh-button");
const runningCount = document.getElementById("running-count");
const configuredCount = document.getElementById("configured-count");
const totalCount = document.getElementById("total-count");

async function fetchBots() {
  const response = await fetch("/api/bots", { cache: "no-store" });
  if (!response.ok) {
    throw new Error("Failed to load bot status");
  }

  return response.json();
}

function formatStartedAt(timestamp) {
  if (!timestamp) {
    return "Not started yet";
  }

  const startedAt = new Date(timestamp * 1000);
  return `Started ${startedAt.toLocaleString()}`;
}

function getStatus(bot) {
  if (bot.running) {
    return { label: "Running", className: "running" };
  }

  if (bot.configured) {
    return { label: "Stopped", className: "stopped" };
  }

  return { label: "Missing token", className: "partial" };
}

async function callAction(botName, action) {
  const response = await fetch(`/api/${action}/${botName}`, { method: "POST" });
  const payload = await response.json();

  if (!response.ok || !payload.ok) {
    throw new Error(payload.message || `Failed to ${action} ${botName}`);
  }

  return payload;
}

function renderBots(bots) {
  botGrid.innerHTML = "";
  runningCount.textContent = bots.filter((bot) => bot.running).length;
  configuredCount.textContent = bots.filter((bot) => bot.configured).length;
  totalCount.textContent = bots.length;

  for (const bot of bots) {
    const fragment = template.content.cloneNode(true);
    const status = getStatus(bot);

    fragment.querySelector(".bot-name").textContent = bot.label;
    fragment.querySelector(".bot-meta").textContent = `${bot.name} | ${bot.token_env}`;
    fragment.querySelector(".configured-detail").textContent = bot.configured
      ? "Token configured in environment."
      : "Missing token in environment.";
    fragment.querySelector(".runtime-detail").textContent = bot.running
      ? `PID ${bot.pid || "n/a"} | ${formatStartedAt(bot.started_at)}`
      : formatStartedAt(bot.started_at);
    fragment.querySelector(".error-detail").textContent = bot.last_error
      ? `Last error: ${bot.last_error}`
      : "";

    const statusPill = fragment.querySelector(".status-pill");
    statusPill.textContent = status.label;
    statusPill.classList.add(status.className);

    fragment.querySelectorAll(".action-button").forEach((button) => {
      button.addEventListener("click", async () => {
        button.disabled = true;
        button.textContent = "Working...";

        try {
          await callAction(bot.name, button.dataset.action);
          await loadBots();
        } catch (error) {
          window.alert(error.message);
        } finally {
          button.disabled = false;
          button.textContent =
            button.dataset.action.charAt(0).toUpperCase() +
            button.dataset.action.slice(1);
        }
      });
    });

    botGrid.appendChild(fragment);
  }
}

async function loadBots() {
  try {
    const payload = await fetchBots();
    renderBots(payload.bots || []);
  } catch (error) {
    botGrid.innerHTML = `<article class="bot-card"><p class="bot-name">Dashboard error</p><p class="bot-detail error-detail">${error.message}</p></article>`;
  }
}

refreshButton.addEventListener("click", () => {
  loadBots();
});

loadBots();
window.setInterval(loadBots, 15000);
