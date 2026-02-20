document.addEventListener("DOMContentLoaded", () => {
  const audioFileInput = document.getElementById("audio-file");
  const dropZone = document.getElementById("drop-zone");
  const processButton = document.getElementById("process-button");
  const transcriptViewer = document.getElementById("transcript-viewer");
  const searchInput = document.getElementById("search-input");
  const audioPlayer = document.getElementById("audio-player");
  const timeline = document.getElementById("visualization");
  const segmentCount = document.getElementById("segment-count");
  const episodeSelect = document.getElementById("episode-select");
  const audioSummaryEl = document.getElementById("audio-summary");
  const fileCountEl = document.getElementById("file-count");
  const fileListEl = document.getElementById("file-list");

  const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:5000" : "";
  const MAX_TOPICS = 5;

  let episodes = [];
  let currentEpisodeIndex = -1;
  let selectedFiles = [];

  function limitTopics(segments) {
    return (segments || []).slice(0, MAX_TOPICS);
  }

  function updateSelectedFilesUI(files) {
    const n = files.length;
    if (fileCountEl) {
      fileCountEl.textContent = n ? `${n} file(s) selected` : "No files selected";
    }
    if (fileListEl) {
      if (!n) {
        fileListEl.textContent = "";
      } else {
        fileListEl.innerHTML = files.map((f, i) => `${i + 1}. ${f.name}`).join("<br>");
      }
    }
  }

  function setSelectedFiles(files) {
    selectedFiles = Array.from(files || []);
    // Keep native file input in sync where supported.
    try {
      const dt = new DataTransfer();
      selectedFiles.forEach((f) => dt.items.add(f));
      audioFileInput.files = dt.files;
    } catch (_) {
      // Some browsers block programmatic assignment; selectedFiles still drives processing.
    }
    updateSelectedFilesUI(selectedFiles);
  }

  function secToClock(seconds) {
    const total = Math.max(0, Math.floor(seconds));
    const hrs = Math.floor(total / 3600);
    const mins = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    if (hrs > 0) {
      return `${hrs}:${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    }
    return `${mins}:${String(secs).padStart(2, "0")}`;
  }

  function highlightText(text, query) {
    if (!query) {
      return text;
    }
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return text.replace(new RegExp(`(${escaped})`, "ig"), "<mark>$1</mark>");
  }

  function setActiveSegment(index) {
    if (!transcriptViewer) {
      return;
    }
    const cards = transcriptViewer.querySelectorAll(".segment");
    cards.forEach((card, idx) => card.classList.toggle("active", idx === index));
  }

  function renderTimeline(items) {
    if (!timeline) {
      return;
    }
    timeline.innerHTML = "";
    if (!items.length) {
      timeline.innerHTML = '<p class="timeline-empty">No segments yet. Click "Process Episodes".</p>';
      return;
    }

    const endMax = Math.max(...items.map((s) => s.end), 1);
    items.forEach((segment, index) => {
      const block = document.createElement("button");
      block.type = "button";
      block.className = "timeline-block";
      const widthPercent = Math.max(8, ((segment.end - segment.start) / endMax) * 100);
      block.style.flex = `${widthPercent} 1 0`;
      block.title = `${segment.title} (${secToClock(segment.start)} - ${secToClock(segment.end)})`;
      block.addEventListener("click", () => {
        audioPlayer.currentTime = segment.start;
        audioPlayer.play();
        setActiveSegment(index);
      });
      timeline.appendChild(block);
    });
  }

  function renderSegments(items, query) {
    if (!transcriptViewer || !segmentCount) {
      return;
    }
    transcriptViewer.innerHTML = "";
    segmentCount.textContent = `${items.length} segment${items.length === 1 ? "" : "s"}`;
    if (!items.length) {
      transcriptViewer.innerHTML = '<p class="timeline-empty">No matching segments found.</p>';
      return;
    }

    items.forEach((segment, index) => {
      const card = document.createElement("article");
      card.className = "segment";
      const keys = (segment.keywords || []).join(", ");
      const exact = segment.exactWords || "";

      card.innerHTML = `
        <h3>${highlightText(segment.title || "Topic Segment", query)}</h3>
        <p><strong>Time:</strong> ${secToClock(segment.start || 0)} - ${secToClock(segment.end || 0)}</p>
        <p><strong>Keywords:</strong> ${highlightText(keys, query)}</p>
        <p>${highlightText(segment.summary || "", query)}</p>
        <p class="exact-words"><strong>Exact words:</strong> ${highlightText(exact, query)}</p>
      `;

      card.addEventListener("click", () => {
        audioPlayer.currentTime = segment.start || 0;
        audioPlayer.play();
        setActiveSegment(index);
      });

      transcriptViewer.appendChild(card);
    });
  }

  function buildAudioSummary(episode) {
    if (!episode) {
      return "No summary generated yet.";
    }
    const segmentSummaries = (episode.segments || [])
      .map((s) => (s.summary || "").trim())
      .filter(Boolean);

    if (segmentSummaries.length) {
      return segmentSummaries.slice(0, 4).join("\n\n");
    }

    const raw = (episode.fullTranscript || "").trim();
    if (!raw) {
      return "No summary generated yet.";
    }
    const short = raw.length > 500 ? `${raw.slice(0, 500)}...` : raw;
    return `Transcript-based summary:\n${short}`;
  }

  function renderAudioSummary(text) {
    if (!audioSummaryEl) {
      return;
    }
    audioSummaryEl.textContent = text && text.trim() ? text : "No summary generated yet.";
  }

  function getCurrentEpisode() {
    if (episodes.length && (currentEpisodeIndex < 0 || currentEpisodeIndex >= episodes.length)) {
      currentEpisodeIndex = 0;
    }
    if (currentEpisodeIndex < 0 || currentEpisodeIndex >= episodes.length) {
      return null;
    }
    return episodes[currentEpisodeIndex];
  }

  function applySearch() {
    const episode = getCurrentEpisode();
    if (!episode) {
      renderTimeline([]);
      renderSegments([], "");
      return;
    }

    const q = searchInput.value.trim().toLowerCase();
    if (!q) {
      const limited = limitTopics(episode.segments);
      renderTimeline(limited);
      renderSegments(limited, "");
      renderAudioSummary(buildAudioSummary(episode));
      return;
    }

    const filtered = episode.segments.filter((segment) => {
      const blob = [
        segment.title || "",
        segment.summary || "",
        (segment.keywords || []).join(" "),
        segment.exactWords || ""
      ].join(" ").toLowerCase();
      return blob.includes(q);
    });

    const limitedFiltered = limitTopics(filtered);
    renderTimeline(limitedFiltered);
    renderSegments(limitedFiltered, q);
    renderAudioSummary(buildAudioSummary(episode));
  }

  function renderEpisodeList() {
    episodeSelect.innerHTML = "";
    if (!episodes.length) {
      const opt = document.createElement("option");
      opt.textContent = "No episode processed";
      opt.value = "";
      episodeSelect.appendChild(opt);
      episodeSelect.disabled = true;
      return;
    }

    episodeSelect.disabled = false;
    episodes.forEach((episode, idx) => {
      const opt = document.createElement("option");
      opt.value = String(idx);
      opt.textContent = episode.name;
      episodeSelect.appendChild(opt);
    });
    episodeSelect.value = String(currentEpisodeIndex);
  }

  async function transcribeFile(file) {
    const data = new FormData();
    data.append("audio", file);

    const res = await fetch(`${API_BASE}/process`, {
      method: "POST",
      body: data
    });

    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(payload.error || `Failed for ${file.name}`);
    }

    return payload;
  }

  processButton.addEventListener("click", async () => {
    const files = selectedFiles.length ? selectedFiles : Array.from(audioFileInput.files || []);
    if (!files.length) {
      alert("Please select one or more audio files.");
      return;
    }

    processButton.disabled = true;
    const originalLabel = processButton.textContent;

    try {
      episodes = [];
      searchInput.value = "";

      for (let i = 0; i < files.length; i += 1) {
        const file = files[i];
        let progress = 1;
        processButton.textContent = `Loading ${progress}%`;
        const progressTimer = setInterval(() => {
          if (progress < 99) {
            progress += 5;
            if (progress > 99) {
              progress = 99;
            }
            processButton.textContent = `Loading ${progress}%`;
          }
        }, 45);
        try {
          const result = await transcribeFile(file);
          episodes.push({
            name: file.name,
            url: URL.createObjectURL(file),
            segments: limitTopics(result.segments),
            fullTranscript: result.fullTranscript || "No transcript returned."
          });
        } catch (fileErr) {
          episodes.push({
            name: file.name,
            url: URL.createObjectURL(file),
            segments: [],
            fullTranscript: `Transcription failed.\nReason: ${fileErr.message || "Unknown error"}`
          });
        } finally {
          clearInterval(progressTimer);
          processButton.textContent = "Loading 100%";
        }
      }

      if (!episodes.length) {
        renderEpisodeList();
        renderTimeline([]);
        renderSegments([], "");
        renderAudioSummary("No summary generated.");
        return;
      }

      currentEpisodeIndex = 0;
      renderEpisodeList();
      const current = getCurrentEpisode();
      if (current && current.url) {
        audioPlayer.src = current.url;
      }
      applySearch();
    } catch (err) {
      alert(`Unexpected failure: ${err.message || "unknown"}`);
    } finally {
      processButton.disabled = false;
      processButton.textContent = "Loading 100% Completed";
      setTimeout(() => {
        processButton.textContent = originalLabel;
      }, 1200);
    }
  });

  episodeSelect.addEventListener("change", () => {
    currentEpisodeIndex = Number(episodeSelect.value);
    const current = getCurrentEpisode();
    if (current) {
      audioPlayer.src = current.url;
    }
    applySearch();
  });

  searchInput.addEventListener("input", applySearch);
  audioFileInput.addEventListener("change", () => {
    setSelectedFiles(audioFileInput.files || []);
  });

  if (dropZone) {
    ["dragenter", "dragover"].forEach((evt) => {
      dropZone.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.add("dragover");
      });
    });

    ["dragleave", "drop"].forEach((evt) => {
      dropZone.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove("dragover");
      });
    });

    dropZone.addEventListener("drop", (e) => {
      const dropped = Array.from((e.dataTransfer && e.dataTransfer.files) || []);
      const audioOnly = dropped.filter((f) => (f.type || "").startsWith("audio/") || /\.(mp3|wav|m4a|aac|ogg|flac|opus|wma|mp4|webm)$/i.test(f.name));
      setSelectedFiles(audioOnly);
    });
  }

  renderEpisodeList();
  renderTimeline([]);
  renderSegments([], "");
  renderAudioSummary("");
});
