// SeenIt Popup — auth + CURRENT page + LIST of clusters (similar articles)
const API_BASE_URL = 'http://localhost:8000/api';

const TRACKED_SITES = [
  "bbc.co.uk",
  "reuters.com",
  "cnn.com",
  "nytimes.com",
  "theguardian.com",
];

// Authentication state
let currentUser = null;
let refreshIntervalId = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  checkAuthStatus();
  setupAuthHandlers();
});

// Check if user is authenticated
function checkAuthStatus() {
  chrome.storage.local.get(['user'], (result) => {
    if (result.user && result.user.email) {
      currentUser = result.user;
      showMainContent();
    } else {
      showAuthContainer();
    }
  });
}

// Show authentication container
function showAuthContainer() {
  document.getElementById('auth-container').classList.add('active');
  document.getElementById('main-content').classList.remove('active');
}

// Show main content
function showMainContent() {
  document.getElementById('auth-container').classList.remove('active');
  document.getElementById('main-content').classList.add('active');
  
  if (currentUser) {
    document.getElementById('user-email').textContent = currentUser.email;
  }
  
  // Initialize main app functionality
  initializeApp();
}

// Initialize main app (clusters + similar articles)
function initializeApp() {
  setupTabs();
  loadCurrent();
  loadClusters();
  loadStats();
  document.getElementById('refresh-current')?.addEventListener('click', loadCurrent);

  const clearAllBtn = document.getElementById('clear-all');
  if (clearAllBtn) {
    clearAllBtn.addEventListener('click', () => {
      if (!confirm('Clear all tracked articles?')) return;
      chrome.storage.local.set({ clusters: {} }, () => {
        loadCurrent();
        loadClusters();
        loadStats();
      });
    });
  }

  if (refreshIntervalId) clearInterval(refreshIntervalId);
  refreshIntervalId = setInterval(() => {
    const listTab = document.getElementById('list');
    if (listTab && listTab.classList.contains('active')) {
      loadClusters();
    }
  }, 3000);
}

// Setup authentication event handlers
function setupAuthHandlers() {
  // Login form
  document.getElementById('login-btn').addEventListener('click', handleLogin);
  document.getElementById('login-password').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleLogin();
  });
  
  // Register form
  document.getElementById('register-btn').addEventListener('click', handleRegister);
  document.getElementById('register-password').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleRegister();
  });
  
  // Toggle between login and register
  document.getElementById('show-register').addEventListener('click', () => {
    document.getElementById('login-form').style.display = 'none';
    document.getElementById('register-form').style.display = 'block';
    clearAuthMessages();
  });
  
  document.getElementById('show-login').addEventListener('click', () => {
    document.getElementById('register-form').style.display = 'none';
    document.getElementById('login-form').style.display = 'block';
    clearAuthMessages();
  });
  
  // Logout
  document.getElementById('logout-btn').addEventListener('click', handleLogout);
}

// Handle login
async function handleLogin() {
  const email = document.getElementById('login-email').value;
  const password = document.getElementById('login-password').value;
  
  if (!email || !password) {
    showAuthError('Please enter both email and password');
    return;
  }
  
  try {
    const response = await fetch(`${API_BASE_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username: email, password }),
    });

    const data = await response.json();

    if (response.ok && data.access_token) {
      currentUser = { email };
      chrome.storage.local.set({
        user: { email },
        token: data.access_token,
      }, () => {
        showAuthSuccess('Login successful!');
        setTimeout(() => {
          showMainContent();
          clearAuthMessages();
        }, 1000);
      });
    } else {
      // Better error messages for login
      let errorMessage = 'Login failed';
      
      if (data.detail) {
        if (typeof data.detail === 'string') {
          // Map technical error codes to user-friendly messages
          if (data.detail === 'LOGIN_BAD_CREDENTIALS') {
            errorMessage = 'Invalid email or password';
          } else if (data.detail === 'LOGIN_USER_NOT_VERIFIED') {
            errorMessage = 'Email not verified. Please check your inbox.';
          } else {
            errorMessage = data.detail;
          }
        }
      }
      
      showAuthError(errorMessage);
    }
  } catch (error) {
    console.error('Login error:', error);
    showAuthError('Failed to connect to server. Make sure the backend is running.');
  }
}

// Handle register
async function handleRegister() {
  const email = document.getElementById('register-email').value;
  const password = document.getElementById('register-password').value;
  
  // Clear previous errors
  clearAuthMessages();

  // Client-side validation
  if (!email) {
    showAuthError('Please enter an email address');
    return;
  }

  if (password.length < 8) {
    showAuthError('Password must be at least 8 characters');
    return;
  }
  
  try {
    const response = await fetch(`${API_BASE_URL}/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, password }),
    });
    
    const data = await response.json();
    
    if (response.ok) {
      showAuthSuccess('Registration successful! Please login.');
      // Switch to login form
      setTimeout(() => {
        document.getElementById('register-form').style.display = 'none';
        document.getElementById('login-form').style.display = 'block';
        document.getElementById('login-email').value = email;
        clearAuthMessages();
      }, 1500);
    } else {
      // Better error handling
      let errorMessage = 'Registration failed';
      
      if (data.detail) {
        if (typeof data.detail === 'string') {
          // Direct string errors from backend (already user-friendly)
          errorMessage = data.detail;
        } else if (Array.isArray(data.detail)) {
          // Pydantic validation errors - extract only the messages
          errorMessage = data.detail
            .map(err => {
              if (err.msg) {
                // Clean up the message
                let msg = err.msg.replace('Value error, ', '');
                // Remove technical email validation details
                if (msg.includes('value is not a valid email address')) {
                  return 'Please enter a valid email address';
                }
                return msg;
              }
              return null;
            })
            .filter(msg => msg !== null)
            .join('. ');
        }
      }
      
      // Log the full error for debugging
      console.error('Registration error details:', data);
      
      showAuthError(errorMessage);
    }
  } catch (error) {
    console.error('Registration error:', error);
    showAuthError('Failed to connect to server. Make sure the backend is running.');
  }
}

// Handle logout
function handleLogout() {
  chrome.storage.local.get(["user"], (res) => {
    const userId = res.user?.email || "anonymous";
    const storageKey = `clusters_${userId}`;

    chrome.storage.local.remove([storageKey, "user", "token"], () => {
      currentUser = null;
      if (refreshIntervalId) {
        clearInterval(refreshIntervalId);
        refreshIntervalId = null;
      }
      showAuthContainer();
      document.getElementById("login-email").value = "";
      document.getElementById("login-password").value = "";
      document.getElementById("register-email").value = "";
      document.getElementById("register-password").value = "";
      clearAuthMessages();
    });
  });
}

// Show error message
function showAuthError(message) {
  const errorEl = document.getElementById('auth-error');
  errorEl.textContent = message;
  errorEl.classList.add('show');
  document.getElementById('auth-success').classList.remove('show');
}

// Show success message
function showAuthSuccess(message) {
  const successEl = document.getElementById('auth-success');
  successEl.textContent = message;
  successEl.classList.add('show');
  document.getElementById('auth-error').classList.remove('show');
}

// Clear auth messages
function clearAuthMessages() {
  document.getElementById('auth-error').classList.remove('show');
  document.getElementById('auth-success').classList.remove('show');
}

// ---------------- Utils ----------------

function isTrackedSite(url) {
  try {
    const hostname = new URL(url).hostname.replace("www.", "");
    return TRACKED_SITES.some((site) => hostname.includes(site));
  } catch {
    return false;
  }
}

function escapeHtml(s) {
  return (s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// Find cluster which contains url
function findClusterForUrl(clustersObj, url) {
  const clusters = Object.values(clustersObj || {});
  return (
    clusters.find((c) => c.currentUrl === url) ||
    clusters.find((c) => (c.articles || []).some((a) => a.url === url)) ||
    null
  );
}


// ---------------- Tabs ----------------

function setupTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".content").forEach((c) => c.classList.remove("active"));

      tab.classList.add("active");
      document.getElementById(tab.dataset.tab).classList.add("active");

      if (tab.dataset.tab === "current") loadCurrent();
      if (tab.dataset.tab === "list") loadClusters();
      if (tab.dataset.tab === "settings") loadStats();
    });
  });
}

// ---------------- Current ----------------

function loadCurrent() {
  const titleEl = document.querySelector("#page-info .page-title");
  const urlEl = document.querySelector("#page-info .page-url");
  const trackingEl = document.getElementById("tracking-status");
  const matchesEl = document.getElementById("current-matches");

  titleEl.textContent = "Loading...";
  urlEl.textContent = "";
  trackingEl.style.display = "none";
  matchesEl.innerHTML = "";

  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs?.[0];
    if (!tab?.url) {
      titleEl.textContent = "No active tab";
      return;
    }

    titleEl.textContent = tab.title || "Untitled";
    urlEl.textContent = tab.url;

    if (isTrackedSite(tab.url)) {
      trackingEl.style.display = "block";
    } else {
      trackingEl.style.display = "none";
    }

    chrome.storage.local.get(["clusters"], (res) => {
      const clusters = res.clusters || {};
      const cluster = findClusterForUrl(clusters, tab.url);

      if (!cluster) {
        matchesEl.innerHTML = `
          <p style="color:#6b7280;margin-top:6px;font-size:13px">
            Not tracked yet for this page.
          </p>
        `;
        return;
      }

      const others = (cluster.articles || []).filter((a) => a.url !== tab.url);

      if (others.length === 0) {
        matchesEl.innerHTML = `
          <div class="list-item">
            <div style="font-weight:600;margin-bottom:6px">Similar articles</div>
            <div style="color:#6b7280;font-size:13px">No similar matches saved yet.</div>
          </div>
        `;
        return;
      }

      // sort by similarity desc
      others.sort((a, b) => (b.similarity || 0) - (a.similarity || 0));

      matchesEl.innerHTML = `
        <div class="list-item">
          <div style="font-weight:600;margin-bottom:6px">Similar articles</div>
          <ul style="padding-left:16px;margin:0">
            ${others
              .map(
                (a) => `
              <li style="font-size:13px;margin-bottom:6px">
                <a href="${escapeHtml(a.url)}" target="_blank">${escapeHtml(a.title)}</a>
                <span style="color:#6b7280;font-size:11px">
                  (${(((a.similarity || 0) * 100)).toFixed(0)}%)
                </span>
              </li>`
              )
              .join("")}
          </ul>
          <div style="font-size:11px;color:#9ca3af;margin-top:6px">
            Last visited: ${cluster.lastVisited ? new Date(cluster.lastVisited).toLocaleString() : "—"}
          </div>
        </div>
      `;
    });
  });
}

// ---------------- List ----------------

function loadClusters() {
  chrome.storage.local.get(["user"], (userRes) => {
    const userId = userRes.user?.email || "anonymous";
    const storageKey = `clusters_${userId}`;

    chrome.storage.local.get([storageKey], (res) => {
      const clusters = res[storageKey] || {};
      const container = document.getElementById("seen-list");

      let entries = Object.values(clusters);

      if (entries.length === 0) {
        container.innerHTML = `<p style="color:#6b7280">No articles yet</p>`;
        return;
      }

      entries.sort((a, b) => new Date(b.lastVisited || 0) - new Date(a.lastVisited || 0));

      container.innerHTML = entries
        .map(
          (cluster) => `
        <div class="list-item">
          <div style="font-weight:600;margin-bottom:6px">
            📌 ${escapeHtml(cluster.representativeTitle || "Cluster")}
          </div>
          <ul style="padding-left:16px;margin:0">
            ${(cluster.articles || [])
              .slice()
              .sort((a, b) => (b.similarity || 0) - (a.similarity || 0))
              .map(
                (a) => `
                <li style="font-size:13px;margin-bottom:6px">
                  <a href="${escapeHtml(a.url)}" target="_blank">${escapeHtml(a.title)}</a>
                  <span style="color:#6b7280;font-size:11px">
                    (${((a.similarity || 0) * 100).toFixed(0)}%)
                  </span>
                </li>
              `
              )
              .join("")}
          </ul>
          <div style="font-size:11px;color:#9ca3af;margin-top:6px">
            Last visited: ${cluster.lastVisited ? new Date(cluster.lastVisited).toLocaleString() : "—"}
          </div>
        </div>
      `
        )
        .join("");
    });
  });
}

// ---------------- Stats ----------------

function loadStats() {
  chrome.storage.local.get(["clusters"], (res) => {
    const clusters = res.clusters || {};

    const totalClusters = Object.keys(clusters).length;
    document.getElementById("total-tracked").textContent = totalClusters;

    const today = new Date().toDateString();
    let todayCount = 0;

    Object.values(clusters).forEach((c) => {
      if (c?.lastVisited && new Date(c.lastVisited).toDateString() === today) {
        todayCount++;
      }
    });

    document.getElementById("today-tracked").textContent = todayCount;
  });
}

// Minimal password strength indicator
document.addEventListener('DOMContentLoaded', () => {
  const passwordInput = document.getElementById('register-password');
  
  if (passwordInput) {
    passwordInput.addEventListener('input', (e) => {
      const password = e.target.value;
      const bar = document.getElementById('password-strength-bar');
      const fill = document.getElementById('password-strength-fill');
      
      if (!password) {
        bar.style.display = 'none';
        return;
      }
      
      bar.style.display = 'block';
      
      // Calculate strength (0-100%)
      let strength = 0;
      if (password.length >= 8) strength += 20;
      if (/[A-Z]/.test(password)) strength += 20;
      if (/[a-z]/.test(password)) strength += 20;
      if (/\d/.test(password)) strength += 20;
      if (/[!@#$%^&*(),.?":{}|<>_\-+=]/.test(password)) strength += 20;
      
      // Set width and color
      fill.style.width = strength + '%';
      
      if (strength <= 40) {
        fill.style.background = '#ef4444'; // Red
      } else if (strength <= 60) {
        fill.style.background = '#f59e0b'; // Orange
      } else if (strength <= 80) {
        fill.style.background = '#eab308'; // Yellow
      } else {
        fill.style.background = '#22c55e'; // Green
      }
    });
  }
});