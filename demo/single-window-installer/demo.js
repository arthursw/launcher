const statePicker = document.querySelector("#state-picker");
const progressLabel = document.querySelector("#progress-label");
const progressValue = document.querySelector("#progress-value");
const progressTrack = document.querySelector("#progress-track");
const progressFill = document.querySelector("#progress-fill");
const statusChip = document.querySelector("#status-chip");
const statusChipText = document.querySelector("#status-chip-text");
const logOutput = document.querySelector("#log-output");
const logStatus = document.querySelector("#log-status");
const pathInput = document.querySelector("#install-path");
const copyButton = document.querySelector("#copy-button");

const stateContent = {
  location: {
    status: "Waiting for you",
    statusClass: "",
    progressLabel: "Choose an installation location",
    progressValue: "Not started",
    progress: 0,
    logStatus: "Waiting for installation location",
    logs: [
      ["INFO", "Launcher 1.3.0 started"],
      ["INFO", "Detected macOS 15.5 (arm64)"],
      ["INFO", "Loaded configuration for ExampleApp"],
      ["INFO", "No saved installation location found"],
      ["INFO", "Recommended destination resolved from OS application data"],
      ["INFO", "Waiting for installation location"],
    ],
  },
  existing: {
    status: "Decision required",
    statusClass: "",
    progressLabel: "Review the existing installation",
    progressValue: "Not started",
    progress: 0,
    logStatus: "Waiting for existing-installation choice",
    logs: [
      ["INFO", "Launcher 1.3.0 started"],
      ["INFO", "Loaded configuration for ExampleApp"],
      ["INFO", "Selected installation root: …/Application Support/ExampleApp"],
      ["INFO", "Checking installation destination"],
      ["INFO", "Launcher installation marker found"],
      ["WARN", "Existing ExampleApp installation requires a decision"],
    ],
  },
  installing: {
    status: "Installing",
    statusClass: "installing",
    progressLabel: "Creating Python environment",
    progressValue: "68%",
    progress: 68,
    logStatus: "Installing dependencies with Wetlands",
    logs: [
      ["INFO", "Using installation root: …/Application Support/ExampleApp"],
      ["INFO", "Fetching release metadata"],
      ["INFO", "Latest release is 2.4.0"],
      ["INFO", "Downloading exampleapp-2.4.0-macos-arm64.tar.gz"],
      ["INFO", "Archive signature verified"],
      ["INFO", "Extracted sources/exampleapp-2.4.0"],
      ["INFO", "Preparing Wetlands environment manager"],
      ["INFO", "Resolving Python 3.13 environment"],
      ["INFO", "Installing 42 packages"],
      ["INFO", "wetlands · linking exampleapp (editable)"],
    ],
  },
  complete: {
    status: "Ready",
    statusClass: "complete",
    progressLabel: "Installation complete",
    progressValue: "100%",
    progress: 100,
    logStatus: "ExampleApp is ready",
    logs: [
      ["INFO", "Using installation root: …/Application Support/ExampleApp"],
      ["INFO", "Release 2.4.0 downloaded and verified"],
      ["INFO", "Created Python 3.13 environment"],
      ["INFO", "Installed 42 packages"],
      ["INFO", "Saved installation state"],
      ["INFO", "Running ExampleApp"],
      ["INFO", "Application reported ready"],
      ["INFO", "Installation completed successfully"],
    ],
  },
  error: {
    status: "Stopped",
    statusClass: "error",
    progressLabel: "Installation stopped",
    progressValue: "18%",
    progress: 18,
    logStatus: "Download failed",
    logs: [
      ["INFO", "Using installation root: …/Application Support/ExampleApp"],
      ["INFO", "Fetching release metadata"],
      ["INFO", "Latest release is 2.4.0"],
      ["INFO", "Downloading exampleapp-2.4.0-macos-arm64.tar.gz"],
      ["WARN", "Download attempt 1 of 3 failed; retrying"],
      ["WARN", "Download attempt 2 of 3 failed; retrying"],
      ["ERROR", "Server returned HTTP 503 after 3 attempts"],
      ["INFO", "No existing installation files were changed"],
    ],
  },
};

let installationTimer = null;

function timestamp(index) {
  const base = new Date();
  base.setHours(10, 42, 13 + index);
  return base.toLocaleTimeString([], { hour12: false });
}

function renderLogs(logs) {
  logOutput.replaceChildren();
  logs.forEach(([level, message], index) => {
    const line = document.createElement("div");
    line.className = `log-line ${level.toLowerCase()}`;
    line.innerHTML = `
      <span class="log-time">${timestamp(index)}</span>
      <span class="log-level">${level}</span>
      <span class="log-message"></span>
    `;
    line.querySelector(".log-message").textContent = message;
    logOutput.append(line);
  });
  logOutput.scrollTop = logOutput.scrollHeight;
}

function setProgress(progress) {
  progressFill.classList.remove("indeterminate");
  progressFill.style.width = `${progress}%`;
  progressTrack.setAttribute("aria-valuenow", String(progress));
}

function showState(state) {
  window.clearInterval(installationTimer);
  installationTimer = null;

  const content = stateContent[state];
  document.querySelectorAll(".task-view").forEach((view) => {
    view.classList.toggle("active", view.dataset.state === state);
  });

  statePicker.value = state;
  progressLabel.textContent = content.progressLabel;
  progressValue.textContent = content.progressValue;
  statusChip.className = `status-chip ${content.statusClass}`;
  statusChipText.textContent = content.status;
  logStatus.textContent = content.logStatus;
  setProgress(content.progress);
  renderLogs(content.logs);

  if (state === "installing") {
    runInstallationDemo();
  }
}

function runInstallationDemo() {
  const milestones = [
    [78, "Installing application", "Linking ExampleApp into its environment…", "Installing ExampleApp"],
    [90, "Checking installation", "Verifying the installed application…", "Verifying installation"],
    [96, "Starting ExampleApp", "Waiting for the application to report ready…", "Starting ExampleApp"],
  ];
  let index = 0;
  const operationTitle = document.querySelector("#operation-title");
  const operationDetail = document.querySelector("#operation-detail");

  installationTimer = window.setInterval(() => {
    if (index === milestones.length) {
      showState("complete");
      return;
    }

    const [progress, title, detail, status] = milestones[index];
    progressValue.textContent = `${progress}%`;
    progressLabel.textContent = title;
    operationTitle.textContent = title;
    operationDetail.textContent = detail;
    logStatus.textContent = status;
    setProgress(progress);

    const message = index === 0
      ? "wetlands · installed exampleapp 2.4.0"
      : index === 1
        ? "Checking application entrypoint"
        : "Running ExampleApp";
    const existing = stateContent.installing.logs;
    renderLogs([...existing, ["INFO", message]]);
    index += 1;
  }, 2100);
}

statePicker.addEventListener("change", (event) => {
  showState(event.target.value);
});

document.querySelectorAll("[data-action]").forEach((button) => {
  button.addEventListener("click", () => {
    const action = button.dataset.action;
    if (action === "continue") {
      showState("existing");
    } else if (action === "use" || action === "replace" || action === "retry") {
      showState("installing");
    } else if (action === "location") {
      showState("location");
    } else if (action === "cancel") {
      const currentLogs = stateContent[statePicker.value].logs;
      renderLogs([...currentLogs, ["INFO", "Launcher cancelled by user"]]);
      logStatus.textContent = "Cancelled";
      statusChipText.textContent = "Cancelled";
    }
  });
});

document.querySelector("#browse-button").addEventListener("click", () => {
  pathInput.value = "/Users/alex/Applications/ExampleApp Data";
  const currentLogs = stateContent.location.logs;
  renderLogs([...currentLogs, ["INFO", "Installation destination changed by user"]]);
  logStatus.textContent = "New destination selected";
});

copyButton.addEventListener("click", async () => {
  const text = [...logOutput.querySelectorAll(".log-line")]
    .map((line) => line.textContent.trim().replace(/\s+/g, " "))
    .join("\n");
  try {
    await navigator.clipboard.writeText(text);
    copyButton.textContent = "Copied";
  } catch {
    copyButton.textContent = "Select log";
  }
  window.setTimeout(() => {
    copyButton.textContent = "Copy";
  }, 1400);
});

const requestedState = new URLSearchParams(window.location.search).get("state");
showState(Object.hasOwn(stateContent, requestedState) ? requestedState : "location");
