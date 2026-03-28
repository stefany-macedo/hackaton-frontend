const CONFIG = {
  BASE_URL: 'http://localhost:8004',
  POLL_INTERVAL_MS: 30000,
};

const ApiService = (() => {
  async function request(method, endpoint, body = null, auth = false) {
    const headers = { 'Content-Type': 'application/json' };

    if (auth) {
      const token = StateManager.getToken();
      if (token) headers.Authorization = `Bearer ${token}`;
    }

    const options = { method, headers };
    if (body) options.body = JSON.stringify(body);

    try {
      const response = await fetch(`${CONFIG.BASE_URL}${endpoint}`, options);
      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        return {
          success: false,
          data: null,
          error: data.detail || data.message || 'Erro na API',
        };
      }

      if (endpoint === '/login') {
        data.token = data.access_token;
      }

      return { success: true, data, error: null };
    } catch (err) {
      console.error('[ApiService] Fetch error:', err);
      return { success: false, data: null, error: 'Servidor offline' };
    }
  }

  return {
    registerUser: (data) => request('POST', '/users', data),
    loginUser: (data) => request('POST', '/login', data),

    getLiveGames: () => request('GET', '/games/live', null, true),
    getUpcomingGames: () => request('GET', '/games/upcoming', null, true),
    getGameMarkets: (matchId) => request('GET', `/games/${matchId}/markets`, null, true),
    getUserProfile: (userId) => request('GET', `/users/${userId}/profile`, null, true),
    getLiveRecommendations: (matchId, userId) =>
      request('GET', `/recommendations/live/${matchId}?user_id=${userId}`, null, true),
    composeCoupon: (data) => request('POST', '/coupon/compose', data, true),
    placeBetApi: (data) => request('POST', '/bets', data, true),
    assistantChat: (data) => request('POST', '/assistant/chat', data, true),
    getLiveGames: () => request('GET', '/games/live', null, true),
    getUpcomingGames: () => request('GET', '/games/upcoming', null, true),
    getGameMarkets: (matchId) => request('GET', `/games/${matchId}/markets`, null, true),
  };
})();

const StateManager = (() => {
  const TOKEN_KEY = 'esporte_da_sorte_token';
  const USER_KEY = 'esporte_da_sorte_user';

  const _state = {
    token: localStorage.getItem(TOKEN_KEY) || null,
    user: JSON.parse(localStorage.getItem(USER_KEY) || 'null'),
    bets: [],
    liveGames: [],
    upcomingGames: [],
    superOdds: [],
    userProfile: null,
    currentMatchId: null,
    currentMarkets: [],
    currentRecommendations: [],
    livePollingId: null,
  };

  const _listeners = {};

  function _emit(event, payload) {
    (_listeners[event] || []).forEach(fn => fn(payload));
  }

  return {
    setSession(token, user) {
      _state.token = token;
      _state.user = user;
      localStorage.setItem(TOKEN_KEY, token);
      localStorage.setItem(USER_KEY, JSON.stringify(user));
      _emit('session:changed', { token, user });
    },

    logout() {
      _state.token = null;
      _state.user = null;
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      this.clearBets();
      this.setUserProfile(null);
      this.setCurrentMatch(null, [], []);
      _emit('session:changed', null);
    },

    getToken() { return _state.token; },
    getUser() { return _state.user; },
    isLoggedIn() { return !!_state.token && !!_state.user; },

    getBets() { return [..._state.bets]; },
    addBet(bet) {
      const idx = _state.bets.findIndex(
        b => b.gameId === bet.gameId && b.selectionKey === bet.selectionKey
      );

      if (idx !== -1) {
        _state.bets.splice(idx, 1);
        _emit('coupon:changed', this.getBets());
        return 'removed';
      }

      _state.bets.push(bet);
      _emit('coupon:changed', this.getBets());
      return 'added';
    },
    removeBetAt(i) {
      _state.bets.splice(i, 1);
      _emit('coupon:changed', this.getBets());
    },
    clearBets() {
      _state.bets = [];
      _emit('coupon:changed', []);
    },

    setLiveGames(games) {
      _state.liveGames = Array.isArray(games) ? games : [];
      _emit('games:live', this.getLiveGames());
    },
    getLiveGames() { return [..._state.liveGames]; },

    setUpcomingGames(games) {
      _state.upcomingGames = Array.isArray(games) ? games : [];
      _emit('games:upcoming', this.getUpcomingGames());
    },
    getUpcomingGames() { return [..._state.upcomingGames]; },

    setSuperOdds(items) {
      _state.superOdds = Array.isArray(items) ? items : [];
      _emit('odds:super', this.getSuperOdds());
    },
    getSuperOdds() { return [..._state.superOdds]; },

    setUserProfile(profile) {
      _state.userProfile = profile;
      _emit('profile:changed', profile);
    },
    getUserProfile() { return _state.userProfile; },

    setCurrentMatch(matchId, markets = [], recommendations = []) {
      _state.currentMatchId = matchId;
      _state.currentMarkets = markets;
      _state.currentRecommendations = recommendations;
      _emit('match:changed', {
        matchId,
        markets,
        recommendations,
      });
    },
    getCurrentMatchId() { return _state.currentMatchId; },
    getCurrentMarkets() { return [..._state.currentMarkets]; },
    getCurrentRecommendations() { return [..._state.currentRecommendations]; },

    startLivePolling(intervalMs = CONFIG.POLL_INTERVAL_MS) {
      if (_state.livePollingId) return;
      _state.livePollingId = setInterval(async () => {
        if (!this.isLoggedIn()) return;
        const res = await ApiService.getLiveGames();
        if (res.success) this.setLiveGames(normalizeLiveGames(res.data));
      }, intervalMs);
    },

    stopLivePolling() {
      if (_state.livePollingId) {
        clearInterval(_state.livePollingId);
        _state.livePollingId = null;
      }
    },

    on(event, fn) {
      if (!_listeners[event]) _listeners[event] = [];
      _listeners[event].push(fn);
    },

    off(event, fn) {
      if (_listeners[event]) {
        _listeners[event] = _listeners[event].filter(f => f !== fn);
      }
    },
  };
})();

const Validators = {
  email: v => /\S+@\S+\.\S+/.test(v),
  name: v => v.trim().length >= 2,
  pass: v => v.length >= 8,
  pass2: v => v === (document.getElementById('reg-pass')?.value || ''),
  cpf: v => v.replace(/\D/g, '').length === 11,
  phone: v => v.replace(/\D/g, '').length >= 10,

  field(input, type) {
    const errMap = {
      email: 'err-email',
      name: 'err-name',
      pass: 'err-pass',
      pass2: 'err-pass2',
    };

    const valid = this[type] ? this[type](input.value) : true;
    const errEl = document.getElementById(errMap[type]);
    const show = !valid && input.value.length > 0;

    if (errEl) errEl.classList.toggle('show', show);
    input.classList.toggle('error', show);
    return valid;
  },

  registerForm() {
    const f = {
      name: document.getElementById('reg-name'),
      email: document.getElementById('reg-email'),
      pass: document.getElementById('reg-pass'),
      pass2: document.getElementById('reg-pass2'),
    };

    return (
      this.field(f.name, 'name') &
      this.field(f.email, 'email') &
      this.field(f.pass, 'pass') &
      this.field(f.pass2, 'pass2')
    );
  },
};

function maskCPF(el) {
  let v = el.value.replace(/\D/g, '').slice(0, 11);
  v = v
    .replace(/(\d{3})(\d)/, '$1.$2')
    .replace(/(\d{3})(\d)/, '$1.$2')
    .replace(/(\d{3})(\d{1,2})$/, '$1-$2');
  el.value = v;
}

function maskPhone(el) {
  let v = el.value.replace(/\D/g, '').slice(0, 11);
  if (v.length > 10) v = v.replace(/^(\d{2})(\d{5})(\d{4})$/, '($1) $2-$3');
  else if (v.length > 6) v = v.replace(/^(\d{2})(\d{4})(\d*)$/, '($1) $2-$3');
  else if (v.length > 2) v = v.replace(/^(\d{2})(\d*)$/, '($1) $2');
  el.value = v;
}

function validateField(input, type) {
  Validators.field(input, type);
}

function normalizeLiveGames(games) {
  return (games || []).map(g => ({
    id: g.id,
    league: g.league,
    team1: g.team1,
    team2: g.team2,
    score1: g.score1 ?? 0,
    score2: g.score2 ?? 0,
    time: String(g.time ?? g.minute ?? '0'),
    status: g.status || 'LIVE',
    o1: g.main_market?.o1 || g.o1 || '-',
    ox: g.main_market?.ox || g.ox || '-',
    o2: g.main_market?.o2 || g.o2 || '-',
  }));
}

function normalizeUpcomingGames(games) {
  return (games || []).map(g => ({
    id: g.id,
    league: g.league,
    team1: g.team1,
    team2: g.team2,
    time: String(g.time ?? ''),
    o1: g.main_market?.o1 || g.o1 || '-',
    ox: g.main_market?.ox || g.ox || '-',
    o2: g.main_market?.o2 || g.o2 || '-',
  }));
}

function formatOdd(value) {
  const n = Number(value);
  if (Number.isNaN(n)) return '-';
  return n.toFixed(2);
}

function getRiskEmoji(risk) {
  if (risk === 'baixo') return '🟢';
  if (risk === 'medio') return '🟡';
  if (risk === 'alto') return '🔴';
  return '⚪';
}

const UI = (() => {
  function $(id) {
    return document.getElementById(id);
  }

  function showToast(msg) {
    const t = $('toast');
    const msgEl = $('toast-msg');
    if (!t || !msgEl) return;
    msgEl.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2800);
  }

  function goTo(screen) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    $(`screen-${screen}`)?.classList.add('active');
    window.scrollTo(0, 0);

    const canvas = $('particles-canvas');
    if (canvas) {
      canvas.style.display = screen === 'home' ? 'none' : 'block';
    }
  }

  function setButtonLoading(btn, loading, label) {
    if (!btn) return;
    if (loading) {
      btn.classList.add('loading');
      btn.dataset.label = btn.textContent;
      btn.textContent = '';
    } else {
      btn.classList.remove('loading');
      btn.textContent = label || btn.dataset.label || 'Enviar';
    }
  }

  function setSidebarActive(el) {
    document.querySelectorAll('.sidebar-item').forEach(i => i.classList.remove('active'));
    el.classList.add('active');
  }

  function renderHeaderProfile() {
    const headerActions = document.querySelector('.header-actions');
    const user = StateManager.getUser();
    const profile = StateManager.getUserProfile();

    if (!headerActions) return;

    if (!StateManager.isLoggedIn()) {
      headerActions.innerHTML = `
        <button class="btn-ghost" onclick="goTo('login')">Entrar</button>
        <button class="btn-register" onclick="goTo('register')">Registrar</button>
      `;
      return;
    }

    headerActions.innerHTML = `
      <div class="profile-chip">
        <span class="profile-chip-name">${user?.email || 'Usuário'}</span>
        <span class="profile-chip-risk">${profile?.profile_type || user?.risk_profile || 'MODERADO'}</span>
      </div>
      <button class="btn-ghost" onclick="logoutUser()">Sair</button>
    `;
  }

  function _liveCardHTML(m, isLive) {
    return `
      <div class="live-card" onclick="openMatchDetails('${m.id}')">
        <div class="card-meta">
          ${isLive ? '<span class="live-tag">● AO VIVO</span>' : ''}
          <span class="card-league">${m.league}</span>
          <span class="card-time">${m.time}${isLive ? "'" : ''}</span>
        </div>

        <div class="card-match">
          <div class="team">
            <span class="team-name">${m.team1}</span>
            ${isLive ? `<span class="team-score">${m.score1}</span>` : ''}
          </div>
          <div class="vs-divider">VS</div>
          <div class="team right">
            <span class="team-name">${m.team2}</span>
            ${isLive ? `<span class="team-score">${m.score2}</span>` : ''}
          </div>
        </div>

        <div class="odds-row">
          <button class="odd-btn" onclick="event.stopPropagation(); quickAddMainOdd('${m.id}','${m.league}','${m.team1} x ${m.team2}','home','${m.team1} vence','${m.o1}')">
            <span class="odd-label">1</span><span class="odd-value">${m.o1}</span>
          </button>
          <button class="odd-btn" onclick="event.stopPropagation(); quickAddMainOdd('${m.id}','${m.league}','${m.team1} x ${m.team2}','draw','Empate','${m.ox}')">
            <span class="odd-label">X</span><span class="odd-value">${m.ox}</span>
          </button>
          <button class="odd-btn" onclick="event.stopPropagation(); quickAddMainOdd('${m.id}','${m.league}','${m.team1} x ${m.team2}','away','${m.team2} vence','${m.o2}')">
            <span class="odd-label">2</span><span class="odd-value">${m.o2}</span>
          </button>
        </div>
      </div>
    `;
  }

  function renderLiveGames(games) {
    const el = $('live-grid');
    if (!el) return;
    el.innerHTML = games.map(m => _liveCardHTML(m, true)).join('');
  }

  function renderUpcomingGames(games) {
    const el = $('upcoming-grid');
    if (!el) return;
    el.innerHTML = games.map(m => _liveCardHTML(m, false)).join('');
  }

  function renderSuperOdds(odds) {
    const el = $('so-items');
    if (!el) return;

    if (!odds.length) {
      el.innerHTML = `
        <div class="so-item">
          <div class="so-teams">Nenhuma super odd disponível</div>
          <div style="font-size:11px;color:var(--text-muted)">Carregue recomendações ao vivo</div>
          <div class="so-odd">--</div>
        </div>
      `;
      return;
    }

    el.innerHTML = odds.map(s => `
      <div class="so-item" onclick="addRecommendationToCouponById('${s.match_id}','${s.selection_key}')">
        <div class="so-teams">${s.match}</div>
        <div style="font-size:11px;color:var(--text-muted)">${s.pick}</div>
        <div class="so-odd">${formatOdd(s.odd)} <span class="so-old">${formatOdd(s.oldOdd)}</span></div>
      </div>
    `).join('');
  }

  function renderCoupon() {
    const bets = StateManager.getBets();
    const count = $('coupon-count');
    const body = $('coupon-body');

    if (count) count.textContent = bets.length;
    if (!body) return;

    if (!bets.length) {
      body.innerHTML = `
        <div class="coupon-empty">
          <div class="coupon-empty-icon">🎯</div>
          <div class="coupon-empty-text">Seu cupom está vazio.<br>Clique em uma odd para começar!</div>
        </div>
      `;
      return;
    }

    const totalOdd = bets.reduce((acc, b) => acc * parseFloat(b.odd), 1);
    const defaultStake = parseFloat($('stake-input')?.value) || 10;

    body.innerHTML = `
      <div class="coupon-bets">
        ${bets.map((b, i) => `
          <div class="coupon-bet-card">
            <span class="cbc-remove" onclick="removeBet(${i})">✕</span>
            <div class="cbc-match">${b.match}</div>
            <div class="cbc-pick">${b.pick}</div>
            <div class="cbc-odd">${formatOdd(b.odd)}</div>
          </div>
        `).join('')}
      </div>

      <button class="btn-secondary btn-smart-coupon" onclick="composeSmartCoupon()">
        🦊 Montar múltipla inteligente
      </button>

      <div class="coupon-stake">
        <label>Valor da aposta (R$)</label>
        <input type="number" id="stake-input" value="${defaultStake}" min="1" oninput="updateStake()">
      </div>

      <div class="coupon-summary">
        <div class="cs-row"><span>Odd Total</span><span class="cs-val">${formatOdd(totalOdd)}</span></div>
        <div class="cs-row"><span>Apostado</span><span class="cs-val" id="stk-val">R$ ${defaultStake.toFixed(2)}</span></div>
        <div class="cs-row total"><span>Ganho Potencial</span><span class="cs-val" id="win-val">R$ ${(defaultStake * totalOdd).toFixed(2)}</span></div>
      </div>

      <button class="btn-primary btn-apostar" onclick="placeBet()">Fazer Aposta 🎯</button>
    `;
  }

  function updateStake() {
    const stake = parseFloat($('stake-input')?.value) || 0;
    const totalOdd = StateManager.getBets().reduce((acc, b) => acc * parseFloat(b.odd), 1);
    const sv = $('stk-val');
    const wv = $('win-val');
    if (sv) sv.textContent = `R$ ${stake.toFixed(2)}`;
    if (wv) wv.textContent = `R$ ${(stake * totalOdd).toFixed(2)}`;
  }

  async function handleRegister(btn) {
    if (!Validators.registerForm()) return;

    const payload = {
      nome: $('reg-name')?.value.trim(),
      sobrenome: $('reg-last')?.value.trim() || null,
      email: $('reg-email')?.value.trim().toLowerCase(),
      cpf: $('reg-cpf')?.value.replace(/\D/g, ''),
      telefone: $('reg-phone')?.value.replace(/\D/g, ''),
      password_hash: $('reg-pass')?.value,
      risk_profile: 'MODERADO',
    };

    setButtonLoading(btn, true);

    const res = await ApiService.registerUser(payload);

    setButtonLoading(btn, false, 'Criar Conta');
    console.log('LOGIN RESPONSE:', res);
    if (!res.success) {
      const err = $('err-pass2');
      if (err) {
        err.textContent = res.error || 'Erro ao criar conta.';
        err.classList.add('show');
      }
      return;
    }

    const loginRes = await ApiService.loginUser({
      email: payload.email,
      password: payload.password_hash,
    });

    if (!loginRes.success) {
      showToast('Conta criada, mas o login falhou.');
      goTo('login');
      return;
    }

    StateManager.setSession(loginRes.data.token, loginRes.data.user);
    goTo('home');
    showToast('Conta criada com sucesso! 🎉');
    await bootstrapHomeData();
  }

  async function handleLogin(btn) {
    const email = $('login-email')?.value.trim().toLowerCase();
    const pass = $('login-pass')?.value;
    const errEl = $('err-login');

    if (!email || !pass) {
      if (errEl) {
        errEl.textContent = 'Preencha todos os campos';
        errEl.classList.add('show');
      }
      return;
    }

    setButtonLoading(btn, true);

    const res = await ApiService.loginUser({ email, password: pass });

    setButtonLoading(btn, false, 'Entrar');

    if (!res.success) {
      if (errEl) {
        errEl.textContent = res.error || 'Erro ao fazer login.';
        errEl.classList.add('show');
      }
      return;
    }

    if (errEl) errEl.classList.remove('show');

    StateManager.setSession(res.data.token, res.data.user);
    goTo('home');
    showToast('Bem-vindo de volta! 👋');
    await bootstrapHomeData();
  }

  async function submitBet() {
    const bets = StateManager.getBets();
    const user = StateManager.getUser();

    if (!user?.id) {
      showToast('Faça login para apostar.');
      return;
    }

    if (!bets.length) {
      showToast('Adicione pelo menos uma aposta no cupom.');
      return;
    }

    const stake = parseFloat($('stake-input')?.value) || 10;
    const totalOdd = bets.reduce((acc, b) => acc * parseFloat(b.odd), 1);

    const payload = {
      user_id: user.id,
      selections: bets.map(b => ({
        match_id: b.gameId,
        market_type: b.marketType || '1x2',
        selection_key: b.selectionKey || b.pick,
        selection_label: b.pick,
        odd_taken: parseFloat(b.odd),
      })),
      stake,
      totalOdd: parseFloat(totalOdd.toFixed(2)),
    };

    const res = await ApiService.placeBetApi(payload);

    if (!res.success) {
      showToast(res.error || 'Erro ao confirmar aposta.');
      return;
    }

    showToast('Aposta confirmada! Boa sorte! 🏆');
    StateManager.clearBets();
    await refreshUserProfile();
  }

  return {
    showToast,
    goTo,
    setSidebarActive,
    renderHeaderProfile,
    renderLiveGames,
    renderUpcomingGames,
    renderSuperOdds,
    renderCoupon,
    updateStake,
    handleRegister,
    handleLogin,
    submitBet,
  };
})();

const FoxAssistant = (() => {
  function $(id) {
    return document.getElementById(id);
  }

  let timerId = null;

  function panelIsOpen() {
    const panel = $('fox-panel');
    if (!panel) return false;
    return !panel.hidden && !panel.hasAttribute('hidden');
  }

  function closePanel() {
    const panel = $('fox-panel');
    const fab = $('fox-fab');

    if (panel) {
      panel.hidden = true;
      panel.setAttribute('hidden', '');
    }
    if (fab) fab.setAttribute('aria-expanded', 'false');

    if (timerId) {
      clearInterval(timerId);
      timerId = null;
    }
  }

  function openPanel() {
    const panel = $('fox-panel');
    const fab = $('fox-fab');

    if (panel) {
      panel.hidden = false;
      panel.removeAttribute('hidden');
    }
    if (fab) fab.setAttribute('aria-expanded', 'true');

    renderWelcomeStory();
    startOddsTimer();
    $('fox-input')?.focus();
  }

  function togglePanel() {
    if (panelIsOpen()) closePanel();
    else openPanel();
  }

  function syncAuth() {
    const box = $('fox-assistant');
    if (!box) return;

    if (StateManager.isLoggedIn()) {
      box.removeAttribute('hidden');
      box.setAttribute('aria-hidden', 'false');
    } else {
      box.setAttribute('hidden', '');
      box.setAttribute('aria-hidden', 'true');
      closePanel();
    }
  }

  function startOddsTimer() {
    const timerEl = document.getElementById('fox-story-timer');
    if (!timerEl) return;

    if (timerId) clearInterval(timerId);

    let remaining = 119;
    const render = () => {
      const mm = String(Math.floor(remaining / 60)).padStart(2, '0');
      const ss = String(remaining % 60).padStart(2, '0');
      timerEl.textContent = `Odds atualizadas em ${mm}:${ss}`;
      remaining = remaining <= 0 ? 119 : remaining - 1;
    };

    render();
    timerId = setInterval(render, 1000);
  }

  function renderWelcomeStory() {
    const story = $('fox-dash-story');
    const league = $('fox-dash-league');
    const profile = StateManager.getUserProfile();

    if (!story) return;

    story.innerHTML = `
      <span class="fox-story-title">Eu sou a Raposa da Sorte — sua IA de leitura de apostas. 🦊</span>
      <p class="fox-story-text">Analiso o mercado, o modelo estatístico e o seu perfil para sugerir entradas mais alinhadas ao seu estilo.</p>
      <div class="fox-story-highlight">
        <div class="fox-story-urgency">Perfil atual: <strong>${profile?.profile_type || 'MODERADO'}</strong></div>
        <div class="fox-story-timer" id="fox-story-timer">Odds atualizadas em 01:59</div>
        <span class="fox-story-highlight-label">O que eu faço</span>
        <strong>Mercado + modelo + perfil do usuário</strong>
        <span>Abra um jogo ou me pergunte qual a melhor entrada para você agora.</span>
        <button type="button" class="fox-story-btn" onclick="composeSmartCoupon()">🧠 Montar múltipla inteligente</button>
        <p class="fox-story-reason">Dica: clique em um jogo ao vivo para eu carregar a análise personalizada daquela partida.</p>
      </div>
    `;

    if (league) {
      league.textContent = profile
        ? `Perfil de risco: ${profile.profile_type} · Score ${profile.risk_score}`
        : 'Perfil ainda não carregado';
    }

    renderRecommendations([]);
  }

  function renderRecommendations(recommendations) {
    const matches = $('fox-dash-matches');
    const extra = $('fox-extra-tickets');
    const currentMatchId = StateManager.getCurrentMatchId();

    if (!matches || !extra) return;

    if (!recommendations.length) {
      matches.innerHTML = `
        <article class="fox-match-card">
          <div class="fox-match-meta">Sem partida selecionada</div>
          <div class="fox-match-teams">
            <span class="fox-match-team fox-match-team--home">Abra um jogo</span>
            <span class="fox-match-vs">·</span>
            <span class="fox-match-team fox-match-team--away">para ver análise</span>
          </div>
        </article>
      `;
      extra.innerHTML = '';
      return;
    }

    matches.innerHTML = recommendations.map((rec, idx) => `
      <article class="fox-match-card">
        <div class="fox-match-meta">${rec.market_type} · ${getRiskEmoji(rec.risk_level)} ${rec.risk_level}</div>
        <div class="fox-match-teams">
          <span class="fox-match-team fox-match-team--home">${rec.selection_label}</span>
          <span class="fox-match-vs">odd</span>
          <span class="fox-match-team fox-match-team--away">${formatOdd(rec.market_odd)}</span>
        </div>
        <div class="fox-prob-legend">
          <span>Modelo: ${(Number(rec.model_probability) * 100).toFixed(1)}%</span>
          <span>Justa: ${formatOdd(rec.model_odd)}</span>
          <span>Edge: ${Number(rec.edge_pct).toFixed(2)}%</span>
        </div>
        <p class="fox-story-text" style="margin-top:10px;">${rec.assistant_text}</p>
        <button class="fox-extra-btn" type="button" onclick="addRecommendationToCoupon(${idx})">
          Adicionar ao cupom
        </button>
      </article>
    `).join('');

    extra.innerHTML = `
      <div class="fox-extra-title">Outras ações</div>
      <div class="fox-extra-list">
        <article class="fox-extra-card">
          <div class="fox-extra-match">Partida selecionada</div>
          <div class="fox-extra-meta">${currentMatchId}</div>
          <div class="fox-extra-reason">Posso explicar por que a principal recomendação foi escolhida, comparar risco ou montar uma múltipla com base no seu perfil.</div>
          <button class="fox-extra-btn" type="button" onclick="askFoxPreset('Qual a melhor aposta para mim agora nesse jogo?')">
            Perguntar à Raposa
          </button>
        </article>
      </div>
    `;
  }

  async function ask(message) {
    const user = StateManager.getUser();
    if (!user?.id) {
      UI.showToast('Faça login para falar com a Raposa.');
      return;
    }

    const story = $('fox-dash-story');
    if (!story) return;

    // 1. Coloca a SUA pergunta na tela (Alinhado à direita)
    story.innerHTML += `
      <div style="margin-top: 16px; text-align: right;">
        <span style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Você</span>
        <p class="fox-story-text" style="background: rgba(255,255,255,0.05); border-radius: 8px; padding: 12px; display: inline-block; margin-top: 4px; border: 1px solid rgba(255,255,255,0.1);">
          ${message}
        </p>
      </div>
    `;

    // 2. Coloca o status de "Digitando / Pensando" da Raposa
    const loadingId = 'loading-' + Date.now();
    story.innerHTML += `
      <div id="${loadingId}" style="margin-top: 16px; text-align: left;">
        <span style="font-size: 11px; color: var(--green); font-weight: bold; text-transform: uppercase;">🦊 Raposa da Sorte</span>
        <p class="fox-story-text" style="margin-top: 4px; color: var(--text-muted); font-style: italic;">
          Analisando o banco de dados e calculando odds...
        </p>
      </div>
    `;

    // Desce a barra de rolagem pro final pra acompanhar o chat
    const panel = document.querySelector('.fox-dash-scroll');
    if (panel) panel.scrollTop = panel.scrollHeight;

    // 3. Manda pro seu FastAPI (LangChain)
    const res = await ApiService.assistantChat({
      user_id: user.id,
      match_id: StateManager.getCurrentMatchId(),
      message: message,
      coupon_matches: StateManager.getBets().map(b => b.gameId),
    });

    // 4. Remove o aviso de "Pensando..."
    const loadingEl = document.getElementById(loadingId);
    if (loadingEl) loadingEl.remove();

    // 5. Cospe a resposta final na tela!
if (!res.success) {
      story.innerHTML += `
        <div style="margin-top: 16px; text-align: left;">
          <span style="font-size: 11px; color: #ff4444; font-weight: bold; text-transform: uppercase;">⚠️ Erro de Conexão</span>
          <p class="fox-story-text" style="margin-top: 4px; border-left: 2px solid #ff4444; padding-left: 10px;">
            ${res.error || 'A Raposa se perdeu nos dados. Tente novamente.'}
          </p>
        </div>
      `;
    } else {
      let respostaFormatada = res.data.answer
        .replace(/\*\*(.*?)\*\*/g, '<strong style="color: white;">$1</strong>') // Negrito
        .replace(/\n/g, '<br><br>'); // Pula linha pra não ficar um blocão de texto

      story.innerHTML += `
        <div style="margin-top: 16px; text-align: left;">
          <span style="font-size: 11px; color: var(--green); font-weight: bold; text-transform: uppercase;">🦊 Raposa da Sorte</span>
          <p class="fox-story-text" style="margin-top: 4px; background: rgba(34, 197, 94, 0.1); border-left: 2px solid var(--green); padding: 12px; border-radius: 0 8px 8px 0; line-height: 1.5;">
            ${respostaFormatada}
          </p>
        </div>
      `;
    }
    // Desce a barra de rolagem de novo
    if (panel) panel.scrollTop = panel.scrollHeight;
  }

  function init() {
    syncAuth();
    StateManager.on('session:changed', syncAuth);

    $('fox-fab')?.addEventListener('click', (e) => {
      e.stopPropagation();
      togglePanel();
    });

    $('fox-close')?.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      closePanel();
    });

    $('fox-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const input = $('fox-input');
      const message = input?.value.trim();
      if (!message) return;
      await ask(message);
      input.value = '';
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && panelIsOpen()) closePanel();
    });
  }

  return {
    init,
    openPanel,
    closePanel,
    renderWelcomeStory,
    renderRecommendations,
    ask,
  };
})();

async function refreshUserProfile() {
  const user = StateManager.getUser();
  if (!user?.id) return;

  const res = await ApiService.getUserProfile(user.id);
  if (res.success) {
    StateManager.setUserProfile(res.data);
    UI.renderHeaderProfile();
  }
}

async function loadSuperOddsFromRecommendations() {
  const user = StateManager.getUser();
  if (!user?.id) return;

  const games = StateManager.getLiveGames().slice(0, 3);
  if (!games.length) {
    StateManager.setSuperOdds([]);
    return;
  }

  const items = [];

  for (const game of games) {
    const recsRes = await ApiService.getLiveRecommendations(game.id, user.id);
    if (!recsRes.success) continue;

    const rec = recsRes.data.recommendations?.[0];
    if (!rec) continue;

    items.push({
      id: `${game.id}_${rec.selection_key}`,
      match_id: game.id,
      selection_key: rec.selection_key,
      match: `${game.team1} x ${game.team2}`,
      pick: rec.selection_label,
      odd: Number(rec.market_odd),
      oldOdd: Number(rec.model_odd),
      league: game.league,
    });
  }

  StateManager.setSuperOdds(items);
}

async function bootstrapHomeData() {
  const [liveRes, upcomingRes] = await Promise.all([
    ApiService.getLiveGames(),
    ApiService.getUpcomingGames(),
  ]);

  if (liveRes.success) {
    StateManager.setLiveGames(normalizeLiveGames(liveRes.data));
  }

  if (upcomingRes.success) {
    StateManager.setUpcomingGames(normalizeUpcomingGames(upcomingRes.data));
  }

  await refreshUserProfile();
  await loadSuperOddsFromRecommendations();

  StateManager.startLivePolling();
}

async function openMatchDetails(matchId) {
  const user = StateManager.getUser();
  if (!user?.id) {
    UI.showToast('Faça login para ver análise do jogo.');
    return;
  }

  const [marketsRes, recsRes] = await Promise.all([
    ApiService.getGameMarkets(matchId),
    ApiService.getLiveRecommendations(matchId, user.id),
  ]);

  if (!marketsRes.success || !recsRes.success) {
    UI.showToast('Não foi possível carregar a análise da partida.');
    return;
  }

  StateManager.setCurrentMatch(
    matchId,
    marketsRes.data.markets || [],
    recsRes.data.recommendations || []
  );

  const league = document.getElementById('fox-dash-league');
  if (league) {
    league.textContent = recsRes.data.assistant_summary || 'Análise carregada';
  }

  FoxAssistant.openPanel();
  FoxAssistant.renderRecommendations(recsRes.data.recommendations || []);
}

function quickAddMainOdd(gameId, league, match, selectionKey, pick, odd) {
  const result = StateManager.addBet({
    gameId,
    league,
    match,
    pick,
    odd: parseFloat(odd),
    marketType: '1x2',
    selectionKey,
  });

  UI.showToast(result === 'added' ? `Odd ${odd} adicionada! 🎯` : 'Aposta removida');
}

function addRecommendationToCoupon(index) {
  const currentMatchId = StateManager.getCurrentMatchId();
  const rec = StateManager.getCurrentRecommendations()[index];
  const liveGame = StateManager.getLiveGames().find(g => g.id === currentMatchId);

  if (!rec || !liveGame) return;

  const result = StateManager.addBet({
    gameId: currentMatchId,
    league: liveGame.league,
    match: `${liveGame.team1} x ${liveGame.team2}`,
    pick: rec.selection_label,
    odd: parseFloat(rec.market_odd),
    marketType: rec.market_type,
    selectionKey: rec.selection_key,
  });

  UI.showToast(result === 'added' ? 'Recomendação adicionada ao cupom! 🦊' : 'Aposta removida');
}

async function addRecommendationToCouponById(matchId, selectionKey) {
  const user = StateManager.getUser();
  if (!user?.id) return;

  const recsRes = await ApiService.getLiveRecommendations(matchId, user.id);
  if (!recsRes.success) {
    UI.showToast('Não foi possível carregar a recomendação.');
    return;
  }

  const rec = (recsRes.data.recommendations || []).find(r => r.selection_key === selectionKey);
  const liveGame = StateManager.getLiveGames().find(g => g.id === matchId);

  if (!rec || !liveGame) return;

  const result = StateManager.addBet({
    gameId: matchId,
    league: liveGame.league,
    match: `${liveGame.team1} x ${liveGame.team2}`,
    pick: rec.selection_label,
    odd: parseFloat(rec.market_odd),
    marketType: rec.market_type,
    selectionKey: rec.selection_key,
  });

  UI.showToast(result === 'added' ? 'Super odd adicionada! ⚡' : 'Aposta removida');
}

async function composeSmartCoupon() {
  const user = StateManager.getUser();
  const profile = StateManager.getUserProfile();
  const games = StateManager.getLiveGames();

  if (!user?.id) {
    UI.showToast('Faça login para montar a múltipla.');
    return;
  }

  if (!games.length) {
    UI.showToast('Nenhum jogo ao vivo disponível.');
    return;
  }

  const res = await ApiService.composeCoupon({
    user_id: user.id,
    matches: games.slice(0, 3).map(g => g.id),
    max_selections: 3,
    target_risk: profile?.profile_type || user.risk_profile || 'MODERADO',
  });

  if (!res.success) {
    UI.showToast(res.error || 'Não foi possível montar a múltipla.');
    return;
  }

  StateManager.clearBets();

  const selections = res.data.coupon?.selections || [];
  selections.forEach(sel => {
    StateManager.addBet({
      gameId: sel.match_id,
      league: 'Cupom Inteligente',
      match: sel.selection_label,
      pick: sel.selection_label,
      odd: parseFloat(sel.market_odd || sel.odd),
      marketType: sel.market_type,
      selectionKey: sel.selection_key,
    });
  });

  UI.showToast('Múltipla inteligente montada! 🦊');

  if (res.data.coupon?.assistant_text) {
    FoxAssistant.openPanel();
    const story = document.getElementById('fox-dash-story');
    if (story) {
      story.innerHTML = `
        <span class="fox-story-title">Raposa da Sorte</span>
        <p class="fox-story-text">${res.data.coupon.assistant_text}</p>
      `;
    }
  }
}

async function askFoxPreset(message) {
  FoxAssistant.openPanel();
  await FoxAssistant.ask(message);
}

function logoutUser() {
  StateManager.logout();
  UI.renderHeaderProfile();
  UI.goTo('login');
  UI.showToast('Sessão encerrada.');
}

function goTo(screen) { UI.goTo(screen); }
function handleRegister(btn) { UI.handleRegister(btn); }
function handleLogin(btn) { UI.handleLogin(btn); }
function setSidebarActive(el) { UI.setSidebarActive(el); }
function addBet(e, ...args) { quickAddMainOdd(...args); }
function removeBet(i) { StateManager.removeBetAt(i); }
function updateStake() { UI.updateStake(); }
function placeBet() { UI.submitBet(); }
function showToast(msg) { UI.showToast(msg); }
function openFoxFromBanner() { FoxAssistant.openPanel(); }
function openFutureDashboard() { window.location.href = 'dashboard-futuro.html'; }

StateManager.on('coupon:changed', () => UI.renderCoupon());
StateManager.on('games:live', (games) => UI.renderLiveGames(games));
StateManager.on('games:upcoming', (games) => UI.renderUpcomingGames(games));
StateManager.on('odds:super', (odds) => UI.renderSuperOdds(odds));
StateManager.on('profile:changed', () => UI.renderHeaderProfile());

(function initParticles() {
  const canvas = document.getElementById('particles-canvas');
  if (!canvas || typeof THREE === 'undefined') return;

  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
  camera.position.z = 28;
  camera.position.y = 8;
  camera.rotation.x = -0.28;

  const COLS = 40;
  const ROWS = 30;
  const geometry = new THREE.BufferGeometry();
  const positions = new Float32Array(COLS * ROWS * 3);
  const colors = new Float32Array(COLS * ROWS * 3);

  let k = 0;
  for (let i = 0; i < ROWS; i++) {
    for (let j = 0; j < COLS; j++) {
      positions[k * 3] = (j - COLS / 2) * 1.2;
      positions[k * 3 + 1] = 0;
      positions[k * 3 + 2] = (i - ROWS / 2) * 1.2;
      colors[k * 3] = 0.22;
      colors[k * 3 + 1] = 0.9;
      colors[k * 3 + 2] = 0.49;
      k++;
    }
  }

  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

  const material = new THREE.PointsMaterial({
    size: 0.08,
    vertexColors: true,
    transparent: true,
    opacity: 0.9,
  });

  const points = new THREE.Points(geometry, material);
  scene.add(points);

  function animate(t) {
    const pos = geometry.attributes.position.array;
    let idx = 0;

    for (let i = 0; i < ROWS; i++) {
      for (let j = 0; j < COLS; j++) {
        const x = (j - COLS / 2) * 1.2;
        const z = (i - ROWS / 2) * 1.2;
        pos[idx * 3 + 1] =
          Math.sin((x + t * 0.0018) * 0.75) * 0.55 +
          Math.cos((z + t * 0.0012) * 0.6) * 0.45;
        idx++;
      }
    }

    geometry.attributes.position.needsUpdate = true;
    points.rotation.y += 0.0008;
    renderer.render(scene, camera);
    requestAnimationFrame(animate);
  }

  requestAnimationFrame(animate);

  window.addEventListener('resize', () => {
    renderer.setSize(window.innerWidth, window.innerHeight);
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
  });
})();

window.addEventListener('load', async () => {
  UI.renderHeaderProfile();
  UI.renderCoupon();
  FoxAssistant.init();

  if (StateManager.isLoggedIn()) {
    UI.goTo('home');
    await bootstrapHomeData();
  } else {
    UI.goTo('login');
  }
});

window.openOddsPage = function () {
  window.location.href = 'odds-jogos.html';
};

window.composeSmartCouponFromOddsPage = async function () {
  await composeSmartCoupon();
};