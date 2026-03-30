// Stock Arena - API Client
const API_BASE = '/api';

function getToken() {
  return localStorage.getItem('sa_token');
}

export function setAuth(token, user) {
  localStorage.setItem('sa_token', token);
  localStorage.setItem('sa_user', JSON.stringify(user));
}

export function getUser() {
  try {
    return JSON.parse(localStorage.getItem('sa_user'));
  } catch { return null; }
}

export function clearAuth() {
  localStorage.removeItem('sa_token');
  localStorage.removeItem('sa_user');
}

async function request(path, options = {}) {
  const token = getToken();
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    clearAuth();
    window.location.hash = '#login';
    throw new Error('인증이 필요합니다');
  }

  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || data.message || '요청 실패');
  return data;
}

// Auth
export const register = (data) => request('/auth/register', { method: 'POST', body: JSON.stringify(data) });
export const login = (data) => request('/auth/login', { method: 'POST', body: JSON.stringify(data) });

// Stocks
export const searchStocks = (q) => request(`/stocks/search?q=${encodeURIComponent(q)}`);
export const getStock = (code) => request(`/stocks/${code}`);

// Orders
export const createOrder = (data) => request('/orders', { method: 'POST', body: JSON.stringify(data) });
export const getOrders = (status = 'PENDING') => request(`/orders?status=${status}`);
export const cancelOrder = (id) => request(`/orders/${id}`, { method: 'DELETE' });

// Portfolio
export const getPortfolio = () => request('/portfolio');

// Rankings
export const getMonthlyRankings = (month = '') => request(`/rankings/monthly?month=${month}`);
export const getCumulativeRankings = () => request('/rankings/cumulative');
export const getDailyRankings = (date = '') => request(`/rankings/daily?date=${date}`);

// Trades
export const getTradeLogs = () => request('/trades');

// Board
export const getPosts = (category = '', page = 1) => request(`/posts?category=${encodeURIComponent(category)}&page=${page}`);
export const createPost = (data) => request('/posts', { method: 'POST', body: JSON.stringify(data) });
export const getPost = (id) => request(`/posts/${id}`);
export const addComment = (postId, data) => request(`/posts/${postId}/comments`, { method: 'POST', body: JSON.stringify(data) });
export const votePost = (postId, data) => request(`/posts/${postId}/vote`, { method: 'POST', body: JSON.stringify(data) });

// Betting
export const getBets = (status = '') => request(`/bets?status=${status}`);
export const createBet = (data) => request('/bets', { method: 'POST', body: JSON.stringify(data) });
export const enterBet = (id, data) => request(`/bets/${id}/enter`, { method: 'POST', body: JSON.stringify(data) });
export const settleBet = (id, data) => request(`/bets/${id}/settle`, { method: 'POST', body: JSON.stringify(data) });
export const getPoints = () => request('/points');

// Attendance
export const checkAttendance = () => request('/attendance/check-in', { method: 'POST' });

// Gacha (일일 가챠 뽑기)
export const getGachaToday = () => request('/gacha/today');
export const spinGacha = () => request('/gacha/spin', { method: 'POST' });
export const getRecentJackpots = () => request('/gacha/recent-jackpots');

// Point Leaderboard
export const getPointLeaderboard = () => request('/points/leaderboard');

// Daily Free Charge & Relief
export const claimDailyFree = () => request('/points/daily-free', { method: 'POST' });
export const claimRelief = () => request('/points/relief', { method: 'POST' });

// RPS (가위바위보)
export const playRPS = (data) => request('/rps/play', { method: 'POST', body: JSON.stringify(data) });
export const getRPSHistory = () => request('/rps/history');

// Point Gift
export const sendPointGift = (data) => request('/points/gift', { method: 'POST', body: JSON.stringify(data) });

// Picks (방's pick)
export const getPicks = () => request('/picks');
export const createPick = (data) => request('/picks', { method: 'POST', body: JSON.stringify(data) });
export const getPick = (id) => request(`/picks/${id}`);
export const addPickComment = (pickId, data) => request(`/picks/${pickId}/comments`, { method: 'POST', body: JSON.stringify(data) });

// Nordle
export const getNordleToday = () => request('/nordle/today');
export const nordleGuess = (guess) => request('/nordle/guess', { method: 'POST', body: JSON.stringify({ guess }) });
export const getNordleLeaderboard = () => request('/nordle/leaderboard');
export const adminSetNordlePuzzle = (data) => request('/nordle/puzzle', { method: 'POST', body: JSON.stringify(data) });

// Dice (주사위 게임)
export const getDiceRooms = () => request('/dice/rooms');
export const createDiceRoom = (data) => request('/dice/rooms', { method: 'POST', body: JSON.stringify(data) });
export const getDiceRoom = (id) => request(`/dice/rooms/${id}`);
export const joinDiceRoom = (id) => request(`/dice/rooms/${id}/join`, { method: 'POST' });
export const toggleDiceReady = (id) => request(`/dice/rooms/${id}/ready`, { method: 'POST' });
export const startDiceRound = (id) => request(`/dice/rooms/${id}/start-round`, { method: 'POST' });
export const rollDice = (id) => request(`/dice/rooms/${id}/roll`, { method: 'POST' });
export const leaveDiceRoom = (id) => request(`/dice/rooms/${id}/leave`, { method: 'POST' });
export const nextDiceGame = (id) => request(`/dice/rooms/${id}/next-game`, { method: 'POST' });
export const cancelDiceRoom = (id) => request(`/dice/rooms/${id}/cancel`, { method: 'POST' });
export const getDiceHistory = () => request('/dice/history');

// Admin
export const adminGetUsers = () => request('/admin/users');
export const adminApproveUser = (data) => request('/admin/users/approve', { method: 'POST', body: JSON.stringify(data) });
export const adminGetIPs = () => request('/admin/ips');
export const adminAddIP = (data) => request('/admin/ips', { method: 'POST', body: JSON.stringify(data) });
export const adminRemoveIP = (ip) => request(`/admin/ips/${ip}`, { method: 'DELETE' });
export const adminGetPendingStocks = () => request('/admin/pending-stocks');
export const adminInputPrices = (data) => request('/admin/prices', { method: 'POST', body: JSON.stringify(data) });
export const adminLoadStocks = (data) => request('/admin/stocks/load-csv', { method: 'POST', body: JSON.stringify(data) });
export const adminMonthReset = (withRewards = false) => request(`/admin/month-reset?with_rewards=${withRewards}`, { method: 'POST' });
export const adminAdjustPoints = (data) => request('/admin/points/adjust', { method: 'POST', body: JSON.stringify(data) });
export const adminGetTransactions = (params = {}) => {
  const q = new URLSearchParams();
  if (params.user_id) q.set('user_id', params.user_id);
  if (params.source) q.set('source', params.source);
  if (params.page) q.set('page', params.page);
  return request(`/admin/points/transactions?${q.toString()}`);
};
export const adminGetDiceRooms = () => request('/admin/dice/rooms');
export const adminDestroyDiceRoom = (id) => request(`/admin/dice/rooms/${id}/destroy`, { method: 'POST' });
