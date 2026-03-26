const ApiService = (() => {
  const BASE_URL = 'http://localhost:8000'; // Apontando pro seu FastAPI!

  async function request(method, endpoint, body = null, auth = false) {
    if (endpoint === '/users' || endpoint === '/login') {
      const headers = { 'Content-Type': 'application/json' };
      const options = { method, headers };
      if (body) options.body = JSON.stringify(body);

      try {
        const response = await fetch(`${BASE_URL}${endpoint}`, options);
        const data = await response.json();

        // Se o FastAPI retornar erro 400, 401, etc.
        if (!response.ok) {
          return { success: false, data: null, error: data.detail || 'Erro na API' };
        }
        
        // No login, o backend devolve 'access_token', mas o front espera 'token'
        if (endpoint === '/login') {
            data.token = data.access_token; 
            data.user = { email: body.email, risk_profile: data.risk_profile };
        }

        return { success: true, data: data, error: null };
      } catch (err) {
        console.error("Erro no Fetch:", err);
        return { success: false, data: null, error: 'Servidor offline' };
      }
    }

    // MOCK DOS JOGOS
    return _mockRouter(method, endpoint, body);
  }

  function _mockRouter(method, endpoint, body) {
    if (endpoint === '/games/live' && method === 'GET') return { success: true, data: _mockLiveGames(), error: null };
    if (endpoint === '/games/upcoming' && method === 'GET') return { success: true, data: _mockUpcomingGames(), error: null };
    if (endpoint === '/odds/super' && method === 'GET') return { success: true, data: _mockSuperOdds(), error: null };
    if (endpoint === '/bets' && method === 'POST') return { success: true, data: { betId: `bet_${Date.now()}`, status: 'confirmed' }, error: null };
    return { success: false, data: null, error: `Endpoint não mapeado: ${endpoint}` };
  }

  function _mockLiveGames() { return [ { id:'g1', league:'Brasileirão', team1:'Flamengo', team2:'Palmeiras', score1:1, score2:1, time:"47", o1:'1.85', ox:'3.20', o2:'4.10' } ]; }
  function _mockUpcomingGames() { return [ { id:'u1', league:'Brasileirão', team1:'Santos', team2:'Botafogo', time:"18:00", o1:'2.50', ox:'3.20', o2:'2.80' } ]; }
  function _mockSuperOdds() { return [ { id:'s1', match:'Flamengo x Palmeiras', pick:'Casa (Flamengo)', odd:'3.20', oldOdd:'1.85', league:'Brasileirão' } ]; }

  return {
    // apontando pra as rotas do fastapi.
    registerUser:   (data) => request('POST', '/users', data),
    loginUser:      (data) => request('POST', '/login', data),
    
    getLiveGames:   ()     => request('GET',  '/games/live',   null, true),
    getUpcomingGames: ()   => request('GET',  '/games/upcoming', null, true),
    getSuperOdds:   ()     => request('GET',  '/odds/super',   null, true),
    placeBetApi:    (data) => request('POST', '/bets',         data, true),
  };
})();

const StateManager = (() => {
  const TOKEN_KEY   = 'esporte_da_sorte_token';
  const USER_KEY    = 'esporte_da_sorte_user';

  const _state = {
    token:         localStorage.getItem(TOKEN_KEY) || null,
    user:          JSON.parse(localStorage.getItem(USER_KEY) || 'null'),
    bets:          [],
    liveGames:     [],
    upcomingGames: [],
    superOdds:     [],
    selectedRisk:  null,
    bannerIdx:     0,
    livePollingId: null,
  };

  const _listeners = {};
  function _emit(event, payload) {
    (_listeners[event] || []).forEach(fn => fn(payload));
  }

  return {
    setSession(token, user) {
      _state.token = token;
      _state.user  = user;
      localStorage.setItem(TOKEN_KEY, token);
      localStorage.setItem(USER_KEY, JSON.stringify(user));
      _emit('session:changed', { token, user });
    },
    getToken()   { return _state.token; },
    getUser()    { return _state.user; },
    isLoggedIn() { return !!_state.token; },
    logout() {
      _state.token = null;
      _state.user  = null;
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      _emit('session:changed', null);
    },

    setRisk(risk)  { _state.selectedRisk = risk; },
    getRisk()      { return _state.selectedRisk; },

    getBets()      { return [..._state.bets]; },
    addBet(bet) {
      const idx = _state.bets.findIndex(b => b.gameId === bet.gameId && b.pick === bet.pick);
      if (idx !== -1) { _state.bets.splice(idx, 1); _emit('coupon:changed', this.getBets()); return 'removed'; }
      _state.bets.push(bet);
      _emit('coupon:changed', this.getBets());
      return 'added';
    },
    removeBetAt(i) { _state.bets.splice(i, 1); _emit('coupon:changed', this.getBets()); },
    clearBets()    { _state.bets = []; _emit('coupon:changed', []); },

    setLiveGames(games)     { _state.liveGames     = games; _emit('games:live',     games); },
    setUpcomingGames(games) { _state.upcomingGames = games; _emit('games:upcoming', games); },
    setSuperOdds(odds)      { _state.superOdds     = odds;  _emit('odds:super',     odds);  },
    getLiveGames()          { return _state.liveGames; },
    getUpcomingGames()      { return _state.upcomingGames; },
    getSuperOdds()          { return _state.superOdds; },

    getBannerIdx()  { return _state.bannerIdx; },
    setBannerIdx(i) { _state.bannerIdx = i; },

    startLivePolling(intervalMs = 30000) {
      if (_state.livePollingId) return;
      _state.livePollingId = setInterval(async () => {
        const res = await ApiService.getLiveGames();
        if (res.success) this.setLiveGames(res.data);
      }, intervalMs);
      console.info(`[StateManager] Live polling started (every ${intervalMs / 1000}s)`);
    },
    stopLivePolling() {
      if (_state.livePollingId) { clearInterval(_state.livePollingId); _state.livePollingId = null; }
    },

    connectWebSocket(url) {
      if (!url) { console.warn('[StateManager] WebSocket URL not provided.'); return; }
      try {
        const ws = new WebSocket(url);
        ws.onopen    = () => console.info('[WS] Connected to', url);
        ws.onmessage = (evt) => {
          try {
            const msg = JSON.parse(evt.data);
            if (msg.type === 'LIVE_UPDATE')  this.setLiveGames(msg.payload);
            if (msg.type === 'ODDS_UPDATE')  _emit('odds:update', msg.payload);
          } catch { console.warn('[WS] Malformed message', evt.data); }
        };
        ws.onerror   = (e) => console.error('[WS] Error', e);
        ws.onclose   = () => { console.warn('[WS] Disconnected. Falling back to polling.'); this.startLivePolling(); };
        return ws;
      } catch(e) {
        console.error('[WS] Could not connect:', e);
        this.startLivePolling();
      }
    },

    on(event, fn)  { if (!_listeners[event]) _listeners[event] = []; _listeners[event].push(fn); },
    off(event, fn) { if (_listeners[event]) _listeners[event] = _listeners[event].filter(f => f !== fn); },
  };
})();


const Validators = {
  email:  v => /\S+@\S+\.\S+/.test(v),
  name:   v => v.trim().length >= 2,
  pass:   v => v.length >= 8,
  pass2:  v => v === (document.getElementById('reg-pass')?.value || ''),
  cpf:    v => v.replace(/\D/g,'').length === 11,
  phone:  v => v.replace(/\D/g,'').length >= 10,

  field(input, type) {
    const errMap = { email:'err-email', name:'err-name', pass:'err-pass', pass2:'err-pass2' };
    const valid  = this[type] ? this[type](input.value) : true;
    const errEl  = document.getElementById(errMap[type]);
    const show   = !valid && input.value.length > 0;
    if (errEl) errEl.classList.toggle('show', show);
    input.classList.toggle('error', show);
    return valid;
  },

  registerForm() {
    const f = {
      name:  document.getElementById('reg-name'),
      email: document.getElementById('reg-email'),
      pass:  document.getElementById('reg-pass'),
      pass2: document.getElementById('reg-pass2'),
    };
    return (
      this.field(f.name,  'name')  &
      this.field(f.email, 'email') &
      this.field(f.pass,  'pass')  &
      this.field(f.pass2, 'pass2')
    );
  },
};

function maskCPF(el) {
  let v = el.value.replace(/\D/g,'').slice(0,11);
  v = v.replace(/(\d{3})(\d)/,'$1.$2').replace(/(\d{3})(\d)/,'$1.$2').replace(/(\d{3})(\d{1,2})$/,'$1-$2');
  el.value = v;
}
function maskPhone(el) {
  let v = el.value.replace(/\D/g,'').slice(0,11);
  if (v.length > 10) v = v.replace(/^(\d{2})(\d{5})(\d{4})$/,'($1) $2-$3');
  else if (v.length > 6) v = v.replace(/^(\d{2})(\d{4})(\d*)$/,'($1) $2-$3');
  else if (v.length > 2) v = v.replace(/^(\d{2})(\d*)$/,'($1) $2');
  el.value = v;
}

function validateField(input, type) { Validators.field(input, type); }


const UI = (() => {

  function showToast(msg) {
    const t = document.getElementById('toast');
    document.getElementById('toast-msg').textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 3000);
  }

  function goTo(screen) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById('screen-' + screen).classList.add('active');
    window.scrollTo(0, 0);
    const canvas = document.getElementById('particles-canvas');
    canvas.style.display = screen === 'home' ? 'none' : 'block';
  }

  function setButtonLoading(btn, loading, label) {
    if (loading) { btn.classList.add('loading'); btn.textContent = ''; }
    else         { btn.classList.remove('loading'); btn.textContent = label; }
  }

  function renderCoupon() {
    const bets  = StateManager.getBets();
    const count = document.getElementById('coupon-count');
    const body  = document.getElementById('coupon-body');
    count.textContent = bets.length;

    if (bets.length === 0) {
      body.innerHTML = `<div class="coupon-empty"><div class="coupon-empty-icon">🎯</div><div class="coupon-empty-text">Seu cupom está vazio.<br>Clique em uma odd para começar!</div></div>`;
      return;
    }

    const totalOdd = bets.reduce((acc, b) => acc * parseFloat(b.odd), 1).toFixed(2);
    body.innerHTML = `
      <div class="coupon-bets">
        ${bets.map((b, i) => `
          <div class="coupon-bet-card">
            <span class="cbc-remove" onclick="UI.removeBetAt(${i})">✕</span>
            <div class="cbc-match">${b.match}</div>
            <div class="cbc-pick">${b.pick}</div>
            <div class="cbc-odd">${b.odd}</div>
          </div>`).join('')}
      </div>
      <div class="coupon-stake">
        <label>Valor da aposta (R$)</label>
        <input type="number" id="stake-input" value="10" min="1" oninput="UI.updateStake()">
      </div>
      <div class="coupon-summary">
        <div class="cs-row"><span>Odd Total</span><span class="cs-val">${totalOdd}</span></div>
        <div class="cs-row"><span>Apostado</span><span class="cs-val" id="stk-val">R$ 10,00</span></div>
        <div class="cs-row total"><span>Ganho Potencial</span><span class="cs-val" id="win-val">R$ ${(10 * totalOdd).toFixed(2)}</span></div>
      </div>
      <button class="btn-primary btn-apostar" onclick="UI.submitBet()">Fazer Aposta 🎯</button>`;
  }

  function _liveCardHTML(m, isLive) {
    const id = m.id || `${m.team1}-${m.team2}`;
    return `<div class="live-card">
      <div class="card-meta">
        ${isLive ? '<span class="live-tag">● AO VIVO</span>' : ''}
        <span class="card-league">${m.league}</span>
        <span class="card-time">${m.time}${isLive ? "'" : ""}</span>
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
        <button class="odd-btn" onclick="UI.addBet(event,'${id}','${m.league}','${m.team1} x ${m.team2}','1 (${m.team1})','${m.o1}')">
          <span class="odd-label">1</span><span class="odd-value">${m.o1}</span>
        </button>
        <button class="odd-btn" onclick="UI.addBet(event,'${id}','${m.league}','${m.team1} x ${m.team2}','X','${m.ox}')">
          <span class="odd-label">X</span><span class="odd-value">${m.ox}</span>
        </button>
        <button class="odd-btn" onclick="UI.addBet(event,'${id}','${m.league}','${m.team1} x ${m.team2}','2 (${m.team2})','${m.o2}')">
          <span class="odd-label">2</span><span class="odd-value">${m.o2}</span>
        </button>
      </div>
    </div>`;
  }

  function renderLiveGames(games) {
    const el = document.getElementById('live-grid');
    if (el) el.innerHTML = games.map(m => _liveCardHTML(m, true)).join('');
  }
  function renderUpcomingGames(games) {
    const el = document.getElementById('upcoming-grid');
    if (el) el.innerHTML = games.map(m => _liveCardHTML(m, false)).join('');
  }
  function renderSuperOdds(odds) {
    const el = document.getElementById('so-items');
    if (el) el.innerHTML = odds.map(s =>
      `<div class="so-item" onclick="UI.addBet(event,'${s.id}','${s.league}','${s.match}','${s.pick}','${s.odd}')">
        <div class="so-teams">${s.match}</div>
        <div style="font-size:11px;color:var(--text-muted)">${s.pick}</div>
        <div class="so-odd">${s.odd} <span class="so-old">${s.oldOdd}</span></div>
      </div>`).join('');
  }

  function setBanner(i) {
    StateManager.setBannerIdx(i);
    document.getElementById('banner-slides').style.transform = `translateX(-${i * 25}%)`;
    document.querySelectorAll('#banner-dots .dot').forEach((d, j) => d.classList.toggle('active', j === i));
  }

  function setSidebarActive(el) {
    document.querySelectorAll('.sidebar-item').forEach(i => i.classList.remove('active'));
    el.classList.add('active');
  }

  return {
    showToast, goTo, setSidebarActive, setBanner, renderCoupon,
    renderLiveGames, renderUpcomingGames, renderSuperOdds,

    async handleRegister(btn) {
      if (!Validators.registerForm()) return;

    const payload = {
      nome:          document.getElementById('reg-name').value.trim(),
      sobrenome:     document.getElementById('reg-last').value.trim(),
      email:         document.getElementById('reg-email').value.trim().toLowerCase(),
      cpf:           document.getElementById('reg-cpf').value.replace(/\D/g,''),
      telefone:      document.getElementById('reg-phone').value.replace(/\D/g,''),
      password_hash: document.getElementById('reg-pass').value, 
      risk_profile:  StateManager.getRisk() || 'MODERADO', // Passando em Maiúsculo
    };

      setButtonLoading(btn, true);

      const res = await ApiService.registerUser(payload);

      setButtonLoading(btn, false, 'Criar Conta');

      if (res.success) {
        StateManager.setSession(`mock_jwt_${Date.now()}`, {
          name: `${payload.nome} ${payload.sobrenome || ''}`.trim() || 'Apostador',
          email: payload.email,
        });
        this.goTo('home');
        this.showToast('Conta criada com sucesso! 🎉');
      } else {
        const err = document.getElementById('err-pass2');
        if (err) { err.textContent = res.error; err.classList.add('show'); }
        console.error('[Register] API error:', res.error);
      }
    },

    async handleLogin(btn) {
      const email = document.getElementById('login-email').value.trim().toLowerCase();
      const pass  = document.getElementById('login-pass').value;
      const errEl = document.getElementById('err-login');

      if (!email || !pass) {
        errEl.textContent = 'Preencha todos os campos';
        errEl.classList.add('show');
        return;
      }

      setButtonLoading(btn, true);

      const res = await ApiService.loginUser({ email: email, password: pass });

      setButtonLoading(btn, false, 'Entrar');

      if (res.success) {
        StateManager.setSession(res.data.token, res.data.user);
        errEl.classList.remove('show');
        this.goTo('home');
        this.showToast('Bem-vindo de volta! 👋');
      } else {
        errEl.textContent = res.error || 'Erro ao fazer login.';
        errEl.classList.add('show');
        console.error('[Login] API error:', res.error);
      }
    },

    addBet(e, gameId, league, match, pick, odd) {
      e.stopPropagation();
      const result = StateManager.addBet({ gameId, league, match, pick, odd });
      this.showToast(result === 'added' ? `Odd ${odd} adicionada! 🎯` : 'Aposta removida');
    },
    addBetFromBanner(league, match, pick, odd) {
      StateManager.addBet({ gameId: `banner_${match}`, league, match, pick, odd });
      this.showToast(`Odd ${odd} adicionada! 🎯`);
    },
    removeBetAt(i) { StateManager.removeBetAt(i); },
    updateStake() {
      const stake    = parseFloat(document.getElementById('stake-input')?.value) || 0;
      const totalOdd = StateManager.getBets().reduce((acc, b) => acc * parseFloat(b.odd), 1);
      const sv = document.getElementById('stk-val');
      const wv = document.getElementById('win-val');
      if (sv) sv.textContent = `R$ ${stake.toFixed(2)}`;
      if (wv) wv.textContent = `R$ ${(stake * totalOdd).toFixed(2)}`;
    },

    async submitBet() {
      const bets     = StateManager.getBets();
      const stake    = parseFloat(document.getElementById('stake-input')?.value) || 10;
      const totalOdd = bets.reduce((acc, b) => acc * parseFloat(b.odd), 1);

      const payload = {
        selections: bets.map(b => ({ gameId: b.gameId, pick: b.pick, odd: parseFloat(b.odd) })),
        stake,
        totalOdd: parseFloat(totalOdd.toFixed(2)),
      };

      const res = await ApiService.placeBetApi(payload);

      if (res.success) {
        this.showToast('Aposta confirmada! Boa sorte! 🏆');
        StateManager.clearBets();
      } else {
        this.showToast('Erro ao confirmar aposta. Tente novamente.');
        console.error('[Bet] API error:', res.error);
      }
    },
  };
})();

function goTo(screen)               { UI.goTo(screen); }
function handleRegister(btn)        { UI.handleRegister(btn); }
function handleLogin(btn)           { UI.handleLogin(btn); }
function setSidebarActive(el)       { UI.setSidebarActive(el); }
function setBanner(i)               { UI.setBanner(i); }
function addBet(e, ...args)         { UI.addBet(e, ...args); }
function addBetFromBanner(...args)  { UI.addBetFromBanner(...args); }
function removeBet(i)               { UI.removeBetAt(i); }
function updateStake()              { UI.updateStake(); }
function placeBet()                 { UI.submitBet(); }
function showToast(msg)             { UI.showToast(msg); }

StateManager.on('coupon:changed', () => UI.renderCoupon());
StateManager.on('games:live',     (games) => UI.renderLiveGames(games));
StateManager.on('games:upcoming', (games) => UI.renderUpcomingGames(games));
StateManager.on('odds:super',     (odds)  => UI.renderSuperOdds(odds));


const FoxAssistant = (() => {
  const FOX_CHAMPIONS_MATCHES = [
    { time: 'Ter · 21:00', home: 'Real Madrid', away: 'Bayern München', pHome: 43, pDraw: 28, pAway: 29 },
    { time: 'Ter · 21:00', home: 'Arsenal', away: 'PSG', pHome: 39, pDraw: 30, pAway: 31 },
    { time: 'Qua · 16:00', home: 'Inter', away: 'Barcelona', pHome: 33, pDraw: 28, pAway: 39 },
    { time: 'Qua · 16:00', home: 'Atlético Madrid', away: 'Borussia Dortmund', pHome: 41, pDraw: 29, pAway: 30 },
  ];

  function $(id) { return document.getElementById(id); }

  function renderFoxDash() {
    const container = $('fox-dash-matches');
    if (!container) return;
    const rows = FOX_CHAMPIONS_MATCHES;
    container.innerHTML = rows.map((m) => `
      <article class="fox-match-card">
        <div class="fox-match-meta">${m.time}</div>
        <div class="fox-match-teams">
          <span class="fox-match-team fox-match-team--home">${m.home}</span>
          <span class="fox-match-vs">vs</span>
          <span class="fox-match-team fox-match-team--away">${m.away}</span>
        </div>
        <div class="fox-prob-bar" role="img" aria-label="Probabilidade 1 ${m.pHome}%, empate ${m.pDraw}%, 2 ${m.pAway}%">
          <div class="fox-prob-seg fox-prob-seg--home" style="width:${m.pHome}%"></div>
          <div class="fox-prob-seg fox-prob-seg--draw" style="width:${m.pDraw}%"></div>
          <div class="fox-prob-seg fox-prob-seg--away" style="width:${m.pAway}%"></div>
        </div>
        <div class="fox-prob-legend">
          <span><span class="fox-dot fox-dot--home"></span>1 ${m.pHome}%</span>
          <span><span class="fox-dot fox-dot--draw"></span>X ${m.pDraw}%</span>
          <span><span class="fox-dot fox-dot--away"></span>2 ${m.pAway}%</span>
        </div>
      </article>`).join('');
  }

  function resetPanel() {
    const container = $('fox-dash-matches');
    if (container) container.innerHTML = '';
    closePanel();
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
      resetPanel();
    }
  }

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
  }

  function openPanel() {
    const panel = $('fox-panel');
    const fab = $('fox-fab');
    if (panel) {
      panel.hidden = false;
      panel.removeAttribute('hidden');
    }
    if (fab) fab.setAttribute('aria-expanded', 'true');
    renderFoxDash();
    $('fox-input')?.focus();
  }

  function togglePanel() {
    if (panelIsOpen()) closePanel();
    else openPanel();
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
    $('fox-form')?.addEventListener('submit', (e) => {
      e.preventDefault();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && panelIsOpen()) closePanel();
    });
  }

  return { init, syncAuth };
})();


(function initParticles() {
  const canvas   = document.getElementById('particles-canvas');
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);

  const scene  = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
  camera.position.z = 28;
  camera.position.y = 8;
  camera.rotation.x = -0.28;

  const COLS = 40, ROWS = 30;
  const geometry  = new THREE.BufferGeometry();
  const positions = new Float32Array(COLS * ROWS * 3);
  const colors    = new Float32Array(COLS * ROWS * 3);

  let k = 0;
  for (let i = 0; i < ROWS; i++) {
    for (let j = 0; j < COLS; j++) {
      positions[k * 3]     = (j - COLS / 2) * 1.2;
      positions[k * 3 + 1] = 0;
      positions[k * 3 + 2] = (i - ROWS / 2) * 1.2;
      colors[k * 3] = 0.22; colors[k * 3 + 1] = 0.9; colors[k * 3 + 2] = 0.49;
      k++;
    }
  }
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('color',    new THREE.BufferAttribute(colors,    3));

  const material = new THREE.PointsMaterial({ size: 0.18, vertexColors: true, transparent: true, opacity: 0.55, sizeAttenuation: true });
  const points   = new THREE.Points(geometry, material);
  scene.add(points);

  let t = 0;
  (function animate() {
    requestAnimationFrame(animate);
    t += 0.018;
    const pos = geometry.attributes.position.array;
    let idx = 0;
    for (let i = 0; i < ROWS; i++) {
      for (let j = 0; j < COLS; j++) {
        pos[idx * 3 + 1] = Math.sin(i * 0.5 + t) * 1.2 + Math.cos(j * 0.4 + t * 0.7) * 0.8;
        idx++;
      }
    }
    geometry.attributes.position.needsUpdate = true;
    points.rotation.y = Math.sin(t * 0.12) * 0.05;
    renderer.render(scene, camera);
  })();

  window.addEventListener('resize', () => {
    renderer.setSize(window.innerWidth, window.innerHeight);
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
  });
})();


const RiskShader = (() => {
  const configs = {
    low:  { base: [5,20,45],   accent: [18,160,90],  speed: 0.55 },
    mid:  { base: [10,15,60],  accent: [56,140,180], speed: 0.90 },
    high: { base: [50,10,40],  accent: [200,80,30],  speed: 1.35 },
  };
  const states = {};

  const VERT = `attribute vec2 a_pos; void main(){gl_Position=vec4(a_pos,0,1);}`;
  const FRAG = `
    precision mediump float;
    uniform float u_time,u_speed,u_hover; uniform vec2 u_res; uniform vec3 u_base,u_accent;
    float noise(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
    float sn(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(noise(i),noise(i+vec2(1,0)),f.x),mix(noise(i+vec2(0,1)),noise(i+vec2(1,1)),f.x),f.y);}
    float fbm(vec2 p){float v=0.,a=.5;for(int i=0;i<4;i++){v+=a*sn(p);p*=2.;a*=.5;}return v;}
    void main(){
      vec2 uv=gl_FragCoord.xy/u_res; uv.y=1.-uv.y;
      float t=u_time*u_speed*(1.+u_hover*.8);
      vec2 q=vec2(fbm(uv+t*.12),fbm(uv+t*.08+1.3));
      vec2 r=vec2(fbm(uv+1.7*q+vec2(1.7,9.2)+t*.15),fbm(uv+1.7*q+vec2(8.3,2.8)+t*.1));
      float f=fbm(uv+1.9*r);
      vec3 col=mix(u_base/255.,u_accent/255.,clamp(f*f*4.,0.,1.));
      col=mix(col,vec3(.22,.9,.49)*.5,clamp(length(q)*.25,0.,.3)*u_hover);
      float edge=length(uv-.5)*2.; col*=1.-edge*.3; col=mix(col,col*1.3,f*.4);
      gl_FragColor=vec4(col*.92,1.);
    }`;

  function _compile(gl, type, src) {
    const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s;
  }
  function _init(id) {
    const canvas = document.getElementById('rc-' + id);
    if (!canvas) return;
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (!gl) return;
    const prog = gl.createProgram();
    gl.attachShader(prog, _compile(gl, gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, _compile(gl, gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog); gl.useProgram(prog);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,1,-1,-1,1,1,1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, 'a_pos');
    gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    states[id] = {
      gl, prog,
      uTime:  gl.getUniformLocation(prog,'u_time'),
      uRes:   gl.getUniformLocation(prog,'u_res'),
      uSpeed: gl.getUniformLocation(prog,'u_speed'),
      uHover: gl.getUniformLocation(prog,'u_hover'),
      uBase:  gl.getUniformLocation(prog,'u_base'),
      uAccent:gl.getUniformLocation(prog,'u_accent'),
      canvas, config: configs[id], hover: 0, t: Math.random() * 100,
    };
  }
  function _resize(id) {
    const s = states[id]; if (!s) return;
    const rect = s.canvas.getBoundingClientRect();
    const dpr  = Math.min(window.devicePixelRatio || 1, 2);
    s.canvas.width  = rect.width  * dpr;
    s.canvas.height = rect.height * dpr;
    s.gl.viewport(0, 0, s.canvas.width, s.canvas.height);
  }
  function _tick() {
    requestAnimationFrame(_tick);
    for (const id in states) {
      const s = states[id]; if (!s) continue;
      if (!s.canvas.width || !s.canvas.height) _resize(id);
      s.t += 0.013;
      const { gl, uTime, uRes, uSpeed, uHover, uBase, uAccent, canvas, config } = s;
      gl.uniform1f(uTime, s.t); gl.uniform2f(uRes, canvas.width, canvas.height);
      gl.uniform1f(uSpeed, config.speed); gl.uniform1f(uHover, s.hover);
      gl.uniform3fv(uBase, config.base); gl.uniform3fv(uAccent, config.accent);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }
  }

  return {
    init() {
      ['low','mid','high'].forEach(id => { _init(id); _resize(id); });
      _tick();
    },
    setHover(id, val)  { if (states[id]) states[id].hover = val; },
    getState(id)       { return states[id]; },
  };
})();

function selectRisk(btn, event) {
  event.preventDefault();
  const risk = btn.dataset.risk;
  document.querySelectorAll('.risk-btn').forEach(b => b.classList.remove('risk-selected'));
  btn.classList.add('risk-selected');
  StateManager.setRisk(risk);
  ['low','mid','high'].forEach(r => RiskShader.setHover(r, r === risk ? 1 : 0));
  const rect = btn.getBoundingClientRect();
  const x = event.clientX - rect.left, y = event.clientY - rect.top;
  const rip = document.getElementById('rrip-' + risk);
  if (rip) {
    const r = document.createElement('div');
    r.className = 'risk-ripple';
    r.style.cssText = `left:${x}px;top:${y}px;width:60px;height:60px;margin:-30px 0 0 -30px`;
    rip.appendChild(r); setTimeout(() => r.remove(), 600);
  }
}
document.querySelectorAll('.risk-btn').forEach(btn => {
  const id = btn.dataset.risk;
  btn.addEventListener('mouseenter', () => { if (!btn.classList.contains('risk-selected')) RiskShader.setHover(id, 1); });
  btn.addEventListener('mouseleave', () => { if (!btn.classList.contains('risk-selected')) RiskShader.setHover(id, 0); });
});


window.addEventListener('load', async () => {

  setTimeout(() => RiskShader.init(), 120);

  setInterval(() => {
    const next = (StateManager.getBannerIdx() + 1) % 4;
    UI.setBanner(next);
  }, 4000);

  const [liveRes, upcomingRes, oddsRes] = await Promise.all([
    ApiService.getLiveGames(),
    ApiService.getUpcomingGames(),
    ApiService.getSuperOdds(),
  ]);

  if (liveRes.success)     StateManager.setLiveGames(liveRes.data);
  if (upcomingRes.success) StateManager.setUpcomingGames(upcomingRes.data);
  if (oddsRes.success)     StateManager.setSuperOdds(oddsRes.data);

  StateManager.startLivePolling(30000);

  UI.renderCoupon();

  FoxAssistant.init();
});
