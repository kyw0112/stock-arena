import { useState, useEffect, useCallback, useRef } from 'react'
import * as api from './api'

// ── Helpers ───────────────────────────────────
const VALID_TABS = ['dashboard', 'trade', 'rankings', 'board', 'picks', 'betting', 'rps', 'dice', 'gacha', 'nordle', 'omok', 'chess', 'shop', 'admin']
const getTabFromHash = () => {
  const h = window.location.hash.replace('#', '')
  return VALID_TABS.includes(h) ? h : 'dashboard'
}

const isExcel = () => document.documentElement.getAttribute('data-theme') === 'excel'
const e = (emoji, text) => isExcel() ? text : emoji

const fmt = (n) => n == null ? '-' : Number(n).toLocaleString('ko-KR')
const fmtRate = (r) => r == null ? '-' : `${r >= 0 ? '+' : ''}${r.toFixed(2)}%`
const rateClass = (r) => r > 0 ? 'profit-positive' : r < 0 ? 'profit-negative' : 'neutral'
const rankClass = (r) => r <= 3 ? `rank-${r}` : ''

// ═══════════════════════════════════════════════
// LOGIN PAGE
// ═══════════════════════════════════════════════
function LoginPage({ onLogin }) {
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({ employee_id: '', password: '', nickname: '' })
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const handleSubmit = async () => {
    setError(''); setSuccess('')
    try {
      if (mode === 'login') {
        const res = await api.login({ employee_id: form.employee_id, password: form.password })
        api.setAuth(res.token, { user_id: res.user_id, nickname: res.nickname, is_admin: res.is_admin })
        onLogin()
      } else {
        await api.register(form)
        setSuccess('가입 완료! 관리자 승인 후 로그인 가능합니다.')
        setMode('login')
      }
    } catch (e) { setError(e.message) }
  }

  return (
    <div className="login-screen">
      <div className="login-box">
        <h1>KIWOOM</h1>
        <p>사내 모의투자 리그</p>
        <input placeholder="사번" value={form.employee_id}
          onChange={e => setForm({...form, employee_id: e.target.value})}
          onKeyDown={e => e.key === 'Enter' && handleSubmit()} />
        {mode === 'register' && (
          <input placeholder="닉네임" value={form.nickname}
            onChange={e => setForm({...form, nickname: e.target.value})} />
        )}
        <input type="password" placeholder="비밀번호" value={form.password}
          onChange={e => setForm({...form, password: e.target.value})}
          onKeyDown={e => e.key === 'Enter' && handleSubmit()} />
        <button className="btn btn-primary btn-block" onClick={handleSubmit}>
          {mode === 'login' ? '로그인' : '가입'}
        </button>
        {error && <div className="login-error">{error}</div>}
        {success && <div className="success-msg">{success}</div>}
        <div className="login-toggle" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError('') }}>
          {mode === 'login' ? '가입하기' : '로그인으로 돌아가기'}
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════
// DASHBOARD (포트폴리오 + 오늘의 랭킹)
// ═══════════════════════════════════════════════
function DashboardPage() {
  const [portfolio, setPortfolio] = useState(null)
  const [rankings, setRankings] = useState([])
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([
      api.getPortfolio().catch(() => null),
      api.getMonthlyRankings().then(r => r.rankings).catch(() => []),
      api.getOrders().catch(() => []),
    ]).then(([p, r, o]) => {
      if (cancelled) return
      setPortfolio(p); setRankings(r); setOrders(o); setLoading(false)
    }).catch(() => {
      if (!cancelled) { setError('데이터를 불러오지 못했습니다'); setLoading(false) }
    })
    return () => { cancelled = true }
  }, [])

  const handleCancel = async (id) => {
    try { await api.cancelOrder(id); setOrders(orders.filter(o => o.id !== id)) } catch {}
  }

  if (loading) return <div className="loading">로딩 중...</div>
  if (error) return <div className="empty">{error}</div>

  return (
    <div>
      {/* 요약 */}
      {portfolio && (
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-label">총 평가액</div>
            <div className="stat-value">{fmt(Math.round(portfolio.total_value))}</div>
            <div className="stat-sub">시드 {fmt(portfolio.initial_seed)}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">수익률</div>
            <div className={`stat-value ${rateClass(portfolio.return_rate)}`}>{fmtRate(portfolio.return_rate)}</div>
            <div className="stat-sub">{portfolio.month}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">현금 잔고</div>
            <div className="stat-value">{fmt(Math.round(portfolio.cash))}</div>
            <div className="stat-sub">투자 {fmt(Math.round(portfolio.total_eval))}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">보유 종목</div>
            <div className="stat-value">{portfolio.holdings.length}</div>
            <div className="stat-sub">개 종목</div>
          </div>
        </div>
      )}

      {/* 보유 종목 */}
      <div className="card">
        <div className="card-title">보유 종목</div>
        {portfolio?.holdings?.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>종목</th>
                  <th className="text-right">수량</th>
                  <th className="text-right">평단가</th>
                  <th className="text-right">현재가</th>
                  <th className="text-right">평가액</th>
                  <th className="text-right">수익률</th>
                </tr>
              </thead>
              <tbody>
                {portfolio.holdings.map(h => (
                  <tr key={h.stock_code}>
                    <td>{h.stock_name} <span className="mono" style={{color:'var(--text-dim)'}}>{h.stock_code}</span></td>
                    <td className="text-right mono">{fmt(h.quantity)}</td>
                    <td className="text-right mono">{fmt(Math.round(h.avg_price))}</td>
                    <td className="text-right mono">{fmt(Math.round(h.current_price))}</td>
                    <td className="text-right mono">{fmt(Math.round(h.eval_amount))}</td>
                    <td className={`text-right mono ${rateClass(h.profit_rate)}`}>{fmtRate(h.profit_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <div className="empty">보유 종목이 없습니다</div>}
      </div>

      {/* 대기 주문 */}
      {orders.length > 0 && (
        <div className="card">
          <div className="card-title">체결 대기 주문</div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>종목</th><th>유형</th><th className="text-right">수량</th><th>시각</th><th></th></tr></thead>
              <tbody>
                {orders.map(o => (
                  <tr key={o.id}>
                    <td>{o.stock_name || o.stock_code}</td>
                    <td><span className={`badge ${o.order_type === 'BUY' ? 'badge-red' : 'badge-blue'}`}>{o.order_type === 'BUY' ? '매수' : '매도'}</span></td>
                    <td className="text-right mono">{fmt(o.quantity)}</td>
                    <td className="mono" style={{fontSize:11,color:'var(--text-dim)'}}>{o.ordered_at}</td>
                    <td className="text-right"><button className="btn btn-ghost btn-sm" onClick={() => handleCancel(o.id)}>취소</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 랭킹 미리보기 */}
      <div className="card">
        <div className="card-title">이번 달 랭킹</div>
        {rankings.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th className="text-center">#</th><th>닉네임</th><th className="text-right">총 평가액</th><th className="text-right">수익률</th></tr></thead>
              <tbody>
                {rankings.slice(0, 10).map(r => (
                  <tr key={r.user_id}>
                    <td className={`text-center ${rankClass(r.rank)}`}>{r.rank}</td>
                    <td>{r.nickname}</td>
                    <td className="text-right mono">{fmt(r.total_value)}</td>
                    <td className={`text-right mono ${rateClass(r.return_rate)}`}>{fmtRate(r.return_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <div className="empty">아직 랭킹 데이터가 없습니다</div>}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════
// TRADE PAGE (종목검색 + 주문)
// ═══════════════════════════════════════════════
function TradePage() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [selected, setSelected] = useState(null)
  const [orderType, setOrderType] = useState('BUY')
  const [quantity, setQuantity] = useState('')
  const [msg, setMsg] = useState({ type: '', text: '' })
  const [trades, setTrades] = useState([])

  useEffect(() => { api.getTradeLogs().then(setTrades).catch(() => {}) }, [])

  const handleSearch = useCallback(async (q) => {
    setQuery(q)
    if (q.length < 1) { setResults([]); return }
    try { setResults(await api.searchStocks(q)) } catch { setResults([]) }
  }, [])

  const handleSelect = async (stock) => {
    setResults([])
    setQuery(stock.name)
    try { setSelected(await api.getStock(stock.code)) } catch {}
  }

  const handleOrder = async () => {
    if (!selected || !quantity) return
    setMsg({ type: '', text: '' })
    try {
      const res = await api.createOrder({ stock_code: selected.code, order_type: orderType, quantity: parseInt(quantity) })
      setMsg({ type: 'success', text: res.message })
      setQuantity('')
    } catch (e) { setMsg({ type: 'error', text: e.message }) }
  }

  return (
    <div>
      {/* 종목 검색 */}
      <div className="card">
        <div className="card-title">종목 검색 & 주문</div>
        <div className="search-box">
          <input placeholder="종목명 또는 코드 검색..." value={query}
            onChange={e => handleSearch(e.target.value)} />
          {results.length > 0 && (
            <div className="search-results">
              {results.map(s => (
                <div key={s.code} className="search-item" onClick={() => handleSelect(s)}>
                  <span>{s.name}</span>
                  <span className="code">{s.code} · {s.market}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {selected && (
          <div>
            <div className="stats-grid" style={{marginBottom:16}}>
              <div className="stat-card">
                <div className="stat-label">{selected.name}</div>
                <div className="stat-value mono">{fmt(selected.last_price || '-')}</div>
                <div className="stat-sub">{selected.last_date ? `${selected.last_date} 종가` : '종가 미등록'}</div>
              </div>
            </div>

            <div className="form-row">
              <div>
                <div className="form-label">주문 유형</div>
                <div style={{display:'flex',gap:8}}>
                  <button className={`btn ${orderType === 'BUY' ? 'btn-buy' : 'btn-ghost'}`}
                    style={{flex:1}} onClick={() => setOrderType('BUY')}>매수</button>
                  <button className={`btn ${orderType === 'SELL' ? 'btn-sell' : 'btn-ghost'}`}
                    style={{flex:1}} onClick={() => setOrderType('SELL')}>매도</button>
                </div>
              </div>
              <div>
                <div className="form-label">수량 (주)</div>
                <input type="number" placeholder="수량 입력" value={quantity}
                  onChange={e => setQuantity(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleOrder()} />
              </div>
              <div style={{display:'flex',alignItems:'flex-end'}}>
                <button className={`btn btn-block ${orderType === 'BUY' ? 'btn-buy' : 'btn-sell'}`} onClick={handleOrder}>
                  {orderType === 'BUY' ? '매수 주문' : '매도 주문'}
                </button>
              </div>
            </div>
            {msg.text && <div className={msg.type === 'error' ? 'error-msg' : 'success-msg'}>{msg.text}</div>}
          </div>
        )}
      </div>

      {/* 거래 내역 */}
      <div className="card">
        <div className="card-title">이번 달 거래 내역</div>
        {trades.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>시각</th><th>종목</th><th>유형</th><th className="text-right">수량</th><th className="text-right">체결가</th><th className="text-right">수수료</th><th className="text-right">세금</th><th className="text-right">금액</th></tr></thead>
              <tbody>
                {trades.map(t => (
                  <tr key={t.id}>
                    <td className="mono" style={{fontSize:11,color:'var(--text-dim)'}}>{t.traded_at}</td>
                    <td>{t.stock_name || t.stock_code}</td>
                    <td><span className={`badge ${t.trade_type === 'BUY' ? 'badge-red' : 'badge-blue'}`}>{t.trade_type === 'BUY' ? '매수' : '매도'}</span></td>
                    <td className="text-right mono">{fmt(t.quantity)}</td>
                    <td className="text-right mono">{fmt(Math.round(t.price))}</td>
                    <td className="text-right mono" style={{color:'var(--text-dim)'}}>{fmt(Math.round(t.fee))}</td>
                    <td className="text-right mono" style={{color:'var(--text-dim)'}}>{fmt(Math.round(t.tax))}</td>
                    <td className="text-right mono">{fmt(Math.round(t.total_amount))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <div className="empty">거래 내역이 없습니다</div>}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════
// RANKINGS PAGE
// ═══════════════════════════════════════════════
function RankingsPage() {
  const [tab, setTab] = useState('monthly')
  const [monthly, setMonthly] = useState([])
  const [cumulative, setCumulative] = useState([])
  const [pointRanks, setPointRanks] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    const p = tab === 'monthly'
      ? api.getMonthlyRankings().then(r => { if (!cancelled) { setMonthly(r.rankings); setLoading(false) } })
      : tab === 'cumulative'
      ? api.getCumulativeRankings().then(r => { if (!cancelled) { setCumulative(r.rankings); setLoading(false) } })
      : api.getPointLeaderboard().then(r => { if (!cancelled) { setPointRanks(r.rankings); setLoading(false) } })
    p.catch(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [tab])

  return (
    <div>
      <div className="card">
        <div className="flex-between mb-16">
          <div className="card-title" style={{margin:0}}>랭킹</div>
          <div style={{display:'flex',gap:4}}>
            <button className={`btn btn-sm ${tab==='monthly'?'btn-primary':'btn-ghost'}`} onClick={()=>setTab('monthly')}>월간</button>
            <button className={`btn btn-sm ${tab==='cumulative'?'btn-primary':'btn-ghost'}`} onClick={()=>setTab('cumulative')}>통산</button>
            <button className={`btn btn-sm ${tab==='points'?'btn-primary':'btn-ghost'}`} onClick={()=>setTab('points')}>포인트</button>
          </div>
        </div>

        {loading ? <div className="loading">로딩 중...</div> : (
          tab === 'monthly' ? (
            monthly.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead><tr><th className="text-center">#</th><th>닉네임</th><th className="text-right">총 평가액</th><th className="text-right">현금</th><th className="text-center">종목 수</th><th className="text-right">수익률</th></tr></thead>
                  <tbody>
                    {monthly.map(r => (
                      <tr key={r.user_id}>
                        <td className={`text-center ${rankClass(r.rank)}`}>{r.rank}</td>
                        <td>{r.badge}{r.badge ? ' ' : ''}{r.nickname}</td>
                        <td className="text-right mono">{fmt(r.total_value)}</td>
                        <td className="text-right mono" style={{color:'var(--text-dim)'}}>{fmt(r.cash)}</td>
                        <td className="text-center">{r.holdings_count}</td>
                        <td className={`text-right mono ${rateClass(r.return_rate)}`} style={{fontWeight:700,fontSize:14}}>{fmtRate(r.return_rate)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <div className="empty">랭킹 데이터가 없습니다</div>
          ) : tab === 'cumulative' ? (
            cumulative.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead><tr><th className="text-center">#</th><th>닉네임</th><th className="text-center">참여 월수</th><th className="text-right">평균 수익률</th><th className="text-right">최고</th><th className="text-right">최저</th><th className="text-right">승률</th></tr></thead>
                  <tbody>
                    {cumulative.map(r => (
                      <tr key={r.user_id}>
                        <td className={`text-center ${rankClass(r.rank)}`}>{r.rank}</td>
                        <td>{r.badge}{r.badge ? ' ' : ''}{r.nickname}</td>
                        <td className="text-center">{r.months_played}</td>
                        <td className={`text-right mono ${rateClass(r.avg_return)}`}>{fmtRate(r.avg_return)}</td>
                        <td className="text-right mono profit-positive">{fmtRate(r.best_return)}</td>
                        <td className="text-right mono profit-negative">{fmtRate(r.worst_return)}</td>
                        <td className="text-right mono">{r.win_rate}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <div className="empty">통산 기록이 없습니다</div>
          ) : (
            pointRanks.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead><tr><th className="text-center">#</th><th>닉네임</th><th className="text-right">포인트</th></tr></thead>
                  <tbody>
                    {pointRanks.map(r => (
                      <tr key={r.user_id}>
                        <td className={`text-center ${rankClass(r.rank)}`}>{r.rank}</td>
                        <td>{r.badge}{r.badge ? ' ' : ''}{r.nickname}</td>
                        <td className="text-right mono" style={{fontWeight:700,color:'var(--orange)'}}>{fmt(r.points)} P</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <div className="empty">포인트 데이터가 없습니다</div>
          )
        )}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════
// BOARD PAGE
// ═══════════════════════════════════════════════
function BoardPage({ onPointsChange }) {
  const [posts, setPosts] = useState([])
  const [viewing, setViewing] = useState(null)
  const [writing, setWriting] = useState(false)
  const [category, setCategory] = useState('')
  const [form, setForm] = useState({ title: '', content: '', category: '자유' })
  const [comment, setComment] = useState('')
  const [pointMsg, setPointMsg] = useState('')
  const categories = ['', '자유', '점심리뷰', '투자이야기', '개발잡담']

  const loadPosts = () => api.getPosts(category).then(setPosts).catch(() => {})

  useEffect(() => { loadPosts() }, [category])

  const showPointMsg = (msg) => { setPointMsg(msg); setTimeout(() => setPointMsg(''), 2500) }

  const handleWrite = async () => {
    try {
      const res = await api.createPost(form)
      setWriting(false); setForm({title:'',content:'',category:'자유'}); loadPosts()
      if (res.points_awarded > 0) { showPointMsg(`+${res.points_awarded}P 적립!`); onPointsChange?.() }
    } catch {}
  }

  const openPost = async (id) => {
    try { setViewing(await api.getPost(id)) } catch {}
  }

  const handleComment = async () => {
    if (!comment.trim() || !viewing) return
    try {
      const res = await api.addComment(viewing.id, {content: comment}); setComment(''); openPost(viewing.id)
      if (res.points_awarded > 0) { showPointMsg(`+${res.points_awarded}P 적립!`); onPointsChange?.() }
    } catch {}
  }

  const handleVote = async (type) => {
    if (!viewing) return
    try { await api.votePost(viewing.id, {vote_type: type}); openPost(viewing.id) } catch {}
  }

  // 게시글 상세
  if (viewing) return (
    <div>
      <button className="btn btn-ghost btn-sm mb-16" onClick={() => setViewing(null)}>← 목록으로</button>
      <div className="card post-detail">
        <div className="flex-between">
          <span className="badge badge-blue">{viewing.category}</span>
          <span style={{fontSize:11,color:'var(--text-dim)'}}>{viewing.created_at}</span>
        </div>
        <h2 style={{fontSize:18,fontWeight:600,margin:'12px 0 4px'}}>{viewing.title}</h2>
        <div style={{fontSize:12,color:'var(--text-dim)'}}>{viewing.nickname}</div>
        <div className="content">{viewing.content}</div>
        <div className="post-actions">
          <button className={`btn btn-sm ${viewing.my_vote === 'like' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => handleVote('like')} disabled={!!viewing.my_vote}>{e('👍','[좋아요]')} {viewing.likes}</button>
          <button className={`btn btn-sm ${viewing.my_vote === 'dislike' ? 'btn-danger' : 'btn-ghost'}`}
            onClick={() => handleVote('dislike')} disabled={!!viewing.my_vote}>{e('👎','[싫어요]')} {viewing.dislikes}</button>
          {viewing.my_vote && <span style={{fontSize:11,color:'var(--text-dim)',alignSelf:'center'}}>투표 완료</span>}
        </div>
      </div>

      <div className="card">
        <div className="card-title">댓글 ({viewing.comments?.length || 0})</div>
        {viewing.comments?.map(c => (
          <div key={c.id} className="comment-item">
            <div className="meta">{c.nickname} · {c.created_at}</div>
            <div className="body">{c.content}</div>
          </div>
        ))}
        <div className="form-row mt-16">
          <input placeholder="댓글 작성..." value={comment}
            onChange={e => setComment(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleComment()} />
          <button className="btn btn-primary" onClick={handleComment} style={{flex:'none'}}>작성</button>
        </div>
        {pointMsg && <div className="success-msg mt-8">{pointMsg}</div>}
      </div>
    </div>
  )

  // 글쓰기
  if (writing) return (
    <div>
      <button className="btn btn-ghost btn-sm mb-16" onClick={() => setWriting(false)}>← 취소</button>
      <div className="card">
        <div className="card-title">글쓰기</div>
        <div className="form-group">
          <div className="form-label">카테고리</div>
          <select value={form.category} onChange={e => setForm({...form, category: e.target.value})}>
            {categories.filter(c => c).map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="form-group">
          <div className="form-label">제목</div>
          <input value={form.title} onChange={e => setForm({...form, title: e.target.value})} />
        </div>
        <div className="form-group">
          <div className="form-label">내용</div>
          <textarea rows={8} value={form.content} onChange={e => setForm({...form, content: e.target.value})} />
        </div>
        <button className="btn btn-primary" onClick={handleWrite}>등록</button>
      </div>
    </div>
  )

  // 목록
  return (
    <div>
      <div className="card">
        <div className="flex-between mb-16">
          <div style={{display:'flex',gap:4,flexWrap:'wrap'}}>
            {categories.map(c => (
              <button key={c||'all'} className={`btn btn-sm ${category===c?'btn-primary':'btn-ghost'}`}
                onClick={() => setCategory(c)}>{c || '전체'}</button>
            ))}
          </div>
          <button className="btn btn-primary btn-sm" onClick={() => setWriting(true)}>글쓰기</button>
        </div>

        {posts.length > 0 ? posts.map(p => (
          <div key={p.id} className="post-item" onClick={() => openPost(p.id)}>
            <div className="post-title"><span className="badge badge-blue" style={{marginRight:8,fontSize:10}}>{p.category}</span>{p.title}</div>
            <div className="post-meta">
              <span>{p.nickname}</span>
              <span>{p.created_at}</span>
              <span>{e('👍','[+]')} {p.likes} {e('👎','[-]')} {p.dislikes}</span>
            </div>
          </div>
        )) : <div className="empty">게시글이 없습니다</div>}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════
// BETTING PAGE
// ═══════════════════════════════════════════════
function BettingPage({ onPointsChange }) {
  const [bets, setBets] = useState([])
  const [points, setPoints] = useState(0)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ title: '', description: '', options: ['', ''], deadline: '' })
  const [entries, setEntries] = useState({})  // {betId: {option, points}}
  const [loading, setLoading] = useState(true)
  const user = api.getUser()

  const load = () => {
    setLoading(true)
    Promise.all([
      api.getBets().catch(() => []),
      api.getPoints().catch(() => ({ points: 0 })),
    ]).then(([b, p]) => {
      setBets(b)
      setPoints(p.points)
      setLoading(false)
    })
  }
  useEffect(load, [])

  const handleCreate = async () => {
    const opts = form.options.filter(o => o.trim())
    if (opts.length < 2) return
    try {
      await api.createBet({ ...form, options: opts })
      setCreating(false); setForm({ title: '', description: '', options: ['', ''], deadline: '' }); load()
    } catch {}
  }

  const handleEnter = async (betId) => {
    const entry = entries[betId]
    if (!entry?.option || !entry?.points) return
    try { await api.enterBet(betId, { chosen_option: entry.option, points: parseInt(entry.points) }); load(); onPointsChange?.() } catch (e) { alert(e.message) }
  }

  const handleSettle = async (betId, result) => {
    try { await api.settleBet(betId, { result }); load() } catch {}
  }

  if (loading) return <div className="loading">로딩 중...</div>

  return (
    <div>
      <div className="flex-between mb-16">
        <div style={{display:'flex',alignItems:'center',gap:12}}>
          <span className="badge badge-orange" style={{fontSize:13,padding:'4px 12px'}}>{e('🎲','[P]')} {fmt(points)} P</span>
        </div>
        <button className="btn btn-primary btn-sm" onClick={() => setCreating(!creating)}>
          {creating ? '취소' : '베팅 만들기'}
        </button>
      </div>

      {creating && (
        <div className="card mb-16">
          <div className="card-title">새 베팅</div>
          <div className="form-group"><div className="form-label">제목</div><input value={form.title} onChange={e=>setForm({...form,title:e.target.value})} /></div>
          <div className="form-group"><div className="form-label">설명</div><textarea rows={2} value={form.description} onChange={e=>setForm({...form,description:e.target.value})} /></div>
          <div className="form-group">
            <div className="form-label">선택지</div>
            {form.options.map((o,i) => (
              <div key={i} className="form-row">
                <input placeholder={`선택지 ${i+1}`} value={o} onChange={e => { const opts = [...form.options]; opts[i] = e.target.value; setForm({...form,options:opts}) }} />
                {i >= 2 && <button className="btn btn-ghost btn-sm" onClick={() => { const opts = form.options.filter((_,j)=>j!==i); setForm({...form,options:opts}) }}>✕</button>}
              </div>
            ))}
            <button className="btn btn-ghost btn-sm" onClick={() => setForm({...form,options:[...form.options,'']})}>+ 선택지 추가</button>
          </div>
          <div className="form-group"><div className="form-label">마감일</div><input type="datetime-local" value={form.deadline} onChange={e=>setForm({...form,deadline:e.target.value.replace('T',' ')})} /></div>
          <button className="btn btn-primary" onClick={handleCreate}>생성</button>
        </div>
      )}

      {bets.map(b => (
        <div key={b.id} className="card bet-card">
          <div className="flex-between">
            <span className={`badge ${b.status==='OPEN'?'badge-green':b.status==='SETTLED'?'badge-blue':'badge-orange'}`}>{b.status}</span>
            <span style={{fontSize:11,color:'var(--text-dim)'}}>{b.entry_count}명 참여 · 마감 {b.deadline}</span>
          </div>
          <h3 style={{fontSize:15,fontWeight:600,margin:'8px 0 4px'}}>{b.title}</h3>
          {b.description && <p style={{fontSize:12,color:'var(--text-dim)',marginBottom:8}}>{b.description}</p>}

          <div className="bet-options">
            {b.options.map(opt => (
              <div key={opt}
                className={`bet-option ${entries[b.id]?.option === opt ? 'selected' : ''} ${b.result === opt ? 'selected' : ''}`}
                onClick={() => b.status === 'OPEN' && setEntries({...entries, [b.id]: {...entries[b.id], option: opt}})}>
                {opt} {b.result === opt && '✓'}
              </div>
            ))}
          </div>

          {b.status === 'OPEN' && (
            <div className="form-row" style={{marginTop:8}}>
              <input type="number" placeholder="포인트" style={{maxWidth:120}}
                value={entries[b.id]?.points || ''} onChange={e => setEntries({...entries, [b.id]: {...entries[b.id], points: e.target.value}})} />
              <button className="btn btn-primary btn-sm" onClick={() => handleEnter(b.id)}>참여</button>
              {user?.is_admin && (
                <select style={{maxWidth:160}} onChange={e => e.target.value && handleSettle(b.id, e.target.value)}>
                  <option value="">정산하기</option>
                  {b.options.map(o => <option key={o} value={o}>{o}</option>)}
                </select>
              )}
            </div>
          )}
        </div>
      ))}
      {bets.length === 0 && <div className="card"><div className="empty">베팅이 없습니다</div></div>}
    </div>
  )
}

// ═══════════════════════════════════════════════
// NORDLE PAGE (수식 맞추기)
// ═══════════════════════════════════════════════
const NORDLE_KEYS = [
  ['7','8','9','+'],
  ['4','5','6','-'],
  ['1','2','3','*'],
  ['0','=','/','DEL','ENTER'],
]

function NordlePage() {
  const [game, setGame] = useState(null)
  const [board, setBoard] = useState([])
  const [leaderboard, setLeaderboard] = useState([])
  const [input, setInput] = useState('')
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [showWeekly, setShowWeekly] = useState(false)
  const [weeklyData, setWeeklyData] = useState(null)
  const user = api.getUser()
  const currentUser = api.getUser()

  const loadWeekly = async () => {
    try { const data = await api.getWeeklyNordleLeaderboard(); setWeeklyData(data); setShowWeekly(true) } catch (e) { alert(e.message) }
  }

  const loadAll = useCallback(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([api.getNordleToday(), api.getNordleLeaderboard()])
      .then(([g, lb]) => {
        if (cancelled) return
        setGame(g)
        setLeaderboard(lb.leaderboard)
        setLoading(false)
      })
      .catch(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  useEffect(loadAll, [loadAll])

  const handleKey = useCallback((k) => {
    if (!game || game.game_over || submitting) return
    if (k === 'DEL') { setInput(p => p.slice(0, -1)); setErr(''); return }
    if (k === 'ENTER') {
      if (input.length !== game.length) { setErr(`수식은 ${game.length}자여야 합니다`); return }
      setSubmitting(true); setErr('')
      api.nordleGuess(input)
        .then(() => { setInput(''); return Promise.all([api.getNordleToday(), api.getNordleLeaderboard()]) })
        .then(([g, lb]) => { setGame(g); setLeaderboard(lb.leaderboard) })
        .catch(e => setErr(e.message))
        .finally(() => setSubmitting(false))
      return
    }
    if (input.length < (game?.length || 8)) { setInput(p => p + k); setErr('') }
  }, [game, input, submitting])

  useEffect(() => {
    if (!game || game.game_over) return
    const allowed = new Set('0123456789+-*/=')
    const onKey = (e) => {
      if (e.key === 'Enter') handleKey('ENTER')
      else if (e.key === 'Backspace') handleKey('DEL')
      else if (allowed.has(e.key)) handleKey(e.key)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [game, handleKey])

  if (loading) return <div className="loading">로딩 중...</div>
  if (!game) return <div className="empty">퍼즐을 불러올 수 없습니다</div>

  const tileColor = (c) => c === 'green' ? 'nordle-green' : c === 'yellow' ? 'nordle-yellow' : c === 'gray' ? 'nordle-gray' : ''

  const rows = Array.from({ length: game.max_attempts }, (_, i) => {
    if (i < game.guesses.length) return { type: 'done', data: game.guesses[i] }
    if (i === game.guesses.length && !game.game_over) return { type: 'input' }
    return { type: 'empty' }
  })

  return (
    <div>
      <div className="card">
        <div className="flex-between mb-16">
          <div className="card-title" style={{margin:0}}>{e('🔢','')} NORDLE</div>
          <div style={{fontSize:12, color:'var(--text-dim)'}}>
            {game.game_over
              ? game.solved
                ? `${e('✅','[O]')} 정답! (${game.guesses.length}/${game.max_attempts}번 만에)`
                : `${e('❌','[X]')} 실패`
              : `${game.guesses.length} / ${game.max_attempts}번 시도`}
          </div>
        </div>

        <p style={{fontSize:12, color:'var(--text-dim)', marginBottom:20, textAlign:'center'}}>
          수식을 {game.max_attempts}번 안에 맞춰보세요 · {e('🟩','[녹]')} 정확한 위치 · {e('🟨','[황]')} 위치 다름 · {e('⬛','[회]')} 없는 글자
        </p>

        {/* 타일 그리드 */}
        <div className="nordle-grid">
          {rows.map((row, ri) => {
            if (row.type === 'done') {
              return (
                <div key={ri} className="nordle-row">
                  {row.data.guess.split('').map((ch, ci) => (
                    <div key={ci} className={`nordle-tile ${tileColor(row.data.colors[ci])}`}>{ch}</div>
                  ))}
                </div>
              )
            }
            if (row.type === 'input') {
              return (
                <div key={ri} className="nordle-row">
                  {Array.from({length: game.length}).map((_, ci) => {
                    const ch = input[ci]
                    const isCursor = ci === input.length
                    return (
                      <div key={ci} className={`nordle-tile ${ch ? 'nordle-filled' : isCursor ? 'nordle-cursor' : 'nordle-empty'}`}>
                        {ch || ''}
                      </div>
                    )
                  })}
                </div>
              )
            }
            return (
              <div key={ri} className="nordle-row">
                {Array.from({length: game.length}).map((_, ci) => (
                  <div key={ci} className="nordle-tile nordle-empty">&nbsp;</div>
                ))}
              </div>
            )
          })}
        </div>

        {err && <div className="error-msg" style={{textAlign:'center', margin:'8px 0'}}>{err}</div>}

        {game.game_over && (
          <div style={{textAlign:'center', margin:'16px 0'}}>
            <div style={{fontSize:12, color:'var(--text-dim)', marginBottom:6}}>정답</div>
            <div className="nordle-answer">{game.answer}</div>
          </div>
        )}

        {/* 키패드 */}
        {!game.game_over && (
          <div className="nordle-keyboard" style={{marginTop:16}}>
            {NORDLE_KEYS.map((row, ri) => (
              <div key={ri} className="nordle-kb-row">
                {row.map(k => (
                  <button
                    key={k}
                    className={`nordle-key ${k === 'ENTER' ? 'nordle-key-enter' : k === 'DEL' ? 'nordle-key-wide' : ''}`}
                    onClick={() => handleKey(k)}
                    disabled={submitting}
                  >{k}</button>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 관리자: 퍼즐 설정 */}
      {user?.is_admin && (
        <div className="card admin-section">
          <div className="card-title">{e('⚙️','')} 오늘의 퍼즐 설정 (관리자)</div>
          <NordleAdminPanel onSaved={loadAll} />
        </div>
      )}

      {/* 리더보드 */}
      <div className="card">
        <div className="flex-between mb-8">
          <div className="card-title" style={{margin:0}}>오늘의 노들 랭킹</div>
          <button className="btn btn-ghost btn-sm" onClick={loadWeekly}>{e('📅','')} 주간</button>
        </div>
        {leaderboard.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th className="text-center">#</th>
                  <th>닉네임</th>
                  <th className="text-center">결과</th>
                  <th className="text-center">시도</th>
                  <th>완료 시각</th>
                </tr>
              </thead>
              <tbody>
                {leaderboard.map(r => (
                  <tr key={r.user_id}>
                    <td className={`text-center ${rankClass(r.rank)}`}>{r.rank}</td>
                    <td>{r.nickname}</td>
                    <td className="text-center">
                      {r.solved
                        ? <span className="badge badge-green">성공</span>
                        : r.attempts >= r.max_attempts
                          ? <span className="badge badge-red">실패</span>
                          : <span className="badge badge-orange">진행중</span>}
                    </td>
                    <td className="text-center mono">{r.attempts} / {r.max_attempts}</td>
                    <td className="mono" style={{fontSize:11, color:'var(--text-dim)'}}>{r.finished_at || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <div className="empty">아직 오늘 참여자가 없습니다</div>}
      </div>

      {/* 주간 리더보드 모달 */}
      {showWeekly && weeklyData && (
        <div className="modal-overlay" onClick={() => setShowWeekly(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="flex-between mb-16">
              <h3 style={{margin:0}}>{e('📅','')} 노들 주간 리더보드</h3>
              <button className="btn btn-ghost" onClick={() => setShowWeekly(false)}>✕</button>
            </div>
            <div style={{fontSize:12,color:'var(--text-dim)',marginBottom:12}}>
              {weeklyData.week_start} ~ {weeklyData.week_end}
              {weeklyData.rewarded && <span className="badge badge-green" style={{marginLeft:8}}>보상 지급 완료</span>}
            </div>
            <div style={{fontSize:12,color:'var(--accent-orange)',marginBottom:12}}>
              주간 보상: 1등 3,000P / 2등 2,000P / 3등 1,000P (풀이 수 기준)
            </div>
            {weeklyData.leaderboard.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>#</th><th>닉네임</th><th>풀이 수</th><th>평균 시도</th><th>최소 시도</th></tr></thead>
                  <tbody>
                    {weeklyData.leaderboard.map((r, i) => (
                      <tr key={r.user_id} className={r.user_id === currentUser?.user_id ? 'highlight-row' : ''}>
                        <td className={rankClass(i+1)}>{i+1} {i < 3 ? ['🥇','🥈','🥉'][i] : ''}</td>
                        <td>{r.nickname}</td>
                        <td className="text-center"><strong>{r.solved_count}</strong></td>
                        <td className="text-center mono">{r.avg_attempts}</td>
                        <td className="text-center mono">{r.best_attempts}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <div className="empty">이번 주 풀이 기록이 없습니다</div>}
          </div>
        </div>
      )}
    </div>
  )
}

function NordleAdminPanel({ onSaved }) {
  const [eq, setEq] = useState('')
  const [msg, setMsg] = useState('')

  const handleSave = async () => {
    setMsg('')
    try {
      const res = await api.adminSetNordlePuzzle({ equation: eq.trim() })
      setMsg(`${e('✅','[OK]')}${res.message}`)
      setEq('')
      onSaved()
    } catch (err) { setMsg(`${e('❌','[ERR]')} ${err.message}`) }
  }

  return (
    <div>
      <div className="form-group">
        <div className="form-label">수식 직접 입력 (비워두면 자동 생성 유지)</div>
        <div className="form-row" style={{alignItems:'flex-end'}}>
          <input
            placeholder="예: 12+34=46"
            value={eq}
            onChange={e => setEq(e.target.value)}
            style={{fontFamily:'var(--mono)', letterSpacing:2}}
          />
          <button className="btn btn-primary" onClick={handleSave} style={{whiteSpace:'nowrap'}}>퍼즐 저장</button>
        </div>
      </div>
      {msg && <div style={{fontSize:12}}>{msg}</div>}
    </div>
  )
}

// ═══════════════════════════════════════════════
// ADMIN PAGE
// ═══════════════════════════════════════════════
// ═══════════════════════════════════════════════
// PICKS PAGE (방's pick)
// ═══════════════════════════════════════════════
function PicksPage() {
  const [picks, setPicks] = useState([])
  const [viewing, setViewing] = useState(null)
  const [writing, setWriting] = useState(false)
  const [form, setForm] = useState({ title: '', content: '', importance: 2, call_date: new Date().toISOString().slice(0,10), call_time: '', stock_codes: '', direction: '매수' })
  const [comment, setComment] = useState('')

  const load = () => api.getPicks().then(setPicks).catch(() => {})
  useEffect(load, [])

  const handleWrite = async () => {
    try { await api.createPick(form); setWriting(false); setForm({ title: '', content: '', importance: 2, call_date: new Date().toISOString().slice(0,10), call_time: '', stock_codes: '', direction: '매수' }); load() } catch {}
  }

  const openPick = async (id) => {
    try { setViewing(await api.getPick(id)) } catch {}
  }

  const handleComment = async () => {
    if (!comment.trim() || !viewing) return
    try { await api.addPickComment(viewing.id, {content: comment}); setComment(''); openPick(viewing.id) } catch {}
  }

  const stars = (n) => '★'.repeat(n) + '☆'.repeat(3-n)
  const dirColor = (d) => d === '매수' ? 'badge-red' : d === '매도' ? 'badge-blue' : 'badge-orange'

  // 상세
  if (viewing) return (
    <div>
      <button className="btn btn-ghost btn-sm mb-16" onClick={() => setViewing(null)}>← 목록으로</button>
      <div className="card">
        <div className="flex-between">
          <div style={{display:'flex',gap:8,alignItems:'center'}}>
            <span style={{color:'#f59e0b',fontSize:16,letterSpacing:2}}>{stars(viewing.importance)}</span>
            {viewing.direction && <span className={`badge ${dirColor(viewing.direction)}`}>{viewing.direction}</span>}
          </div>
          <span style={{fontSize:11,color:'var(--text-dim)'}}>발언일: {viewing.call_date} {viewing.call_time || ''}</span>
        </div>
        <h2 style={{fontSize:18,fontWeight:600,margin:'12px 0 4px'}}>{viewing.title}</h2>
        <div style={{fontSize:12,color:'var(--text-dim)'}}>{viewing.nickname} · {viewing.created_at}</div>

        {viewing.stocks?.length > 0 && (
          <div style={{display:'flex',gap:6,flexWrap:'wrap',margin:'12px 0'}}>
            {viewing.stocks.map(s => (
              <span key={s.code} className="badge badge-blue" style={{fontSize:11}}>{s.name} ({s.code})</span>
            ))}
          </div>
        )}

        <div style={{lineHeight:1.7,margin:'16px 0',whiteSpace:'pre-wrap'}}>{viewing.content}</div>
      </div>

      <div className="card">
        <div className="card-title">댓글 ({viewing.comments?.length || 0})</div>
        {viewing.comments?.map(c => (
          <div key={c.id} className="comment-item">
            <div className="meta">{c.nickname} · {c.created_at}</div>
            <div className="body">{c.content}</div>
          </div>
        ))}
        <div className="form-row mt-16">
          <input placeholder="댓글 작성..." value={comment}
            onChange={e => setComment(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleComment()} />
          <button className="btn btn-primary" onClick={handleComment} style={{flex:'none'}}>작성</button>
        </div>
      </div>
    </div>
  )

  // 작성
  if (writing) return (
    <div>
      <button className="btn btn-ghost btn-sm mb-16" onClick={() => setWriting(false)}>← 취소</button>
      <div className="card">
        <div className="card-title">방's pick 등록</div>
        <div className="form-group"><div className="form-label">제목</div><input value={form.title} onChange={e => setForm({...form, title: e.target.value})} /></div>
        <div className="form-row">
          <div>
            <div className="form-label">중요도</div>
            <div style={{display:'flex',gap:4}}>
              {[1,2,3].map(n => (
                <button key={n} className={`btn btn-sm ${form.importance===n?'btn-primary':'btn-ghost'}`}
                  onClick={() => setForm({...form,importance:n})}>{stars(n)}</button>
              ))}
            </div>
          </div>
          <div>
            <div className="form-label">방향</div>
            <select value={form.direction} onChange={e => setForm({...form, direction: e.target.value})}>
              {['매수','매도','관망','중립'].map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
        </div>
        <div className="form-row">
          <div><div className="form-label">발언일</div><input type="date" value={form.call_date} onChange={e => setForm({...form, call_date: e.target.value})} /></div>
          <div><div className="form-label">시간</div><input type="time" value={form.call_time} onChange={e => setForm({...form, call_time: e.target.value})} /></div>
        </div>
        <div className="form-group"><div className="form-label">관련 종목코드 (쉼표 구분)</div><input placeholder="005930,000660" value={form.stock_codes} onChange={e => setForm({...form, stock_codes: e.target.value})} /></div>
        <div className="form-group"><div className="form-label">내용</div><textarea rows={6} value={form.content} onChange={e => setForm({...form, content: e.target.value})} /></div>
        <button className="btn btn-primary" onClick={handleWrite}>등록</button>
      </div>
    </div>
  )

  // 목록
  return (
    <div>
      <div className="flex-between mb-16">
        <div className="card-title" style={{margin:0}}>방's pick</div>
        <button className="btn btn-primary btn-sm" onClick={() => setWriting(true)}>Pick 등록</button>
      </div>

      {picks.length > 0 ? picks.map(p => (
        <div key={p.id} className="card" style={{cursor:'pointer',marginBottom:10}} onClick={() => openPick(p.id)}>
          <div className="flex-between" style={{marginBottom:6}}>
            <div style={{display:'flex',gap:8,alignItems:'center'}}>
              <span style={{color:'#f59e0b',fontSize:13,letterSpacing:1}}>{stars(p.importance)}</span>
              {p.direction && <span className={`badge ${dirColor(p.direction)}`} style={{fontSize:10}}>{p.direction}</span>}
              <span style={{fontSize:14,fontWeight:600}}>{p.title}</span>
            </div>
            <span className="mono" style={{fontSize:11,color:'var(--text-dim)'}}>{p.call_date} {p.call_time||''}</span>
          </div>
          <div style={{display:'flex',gap:6,flexWrap:'wrap',marginBottom:4}}>
            {p.stocks?.map(s => (
              <span key={s.code} className="badge badge-blue" style={{fontSize:10}}>{s.name}</span>
            ))}
          </div>
          <div style={{fontSize:11,color:'var(--text-dim)',display:'flex',gap:12}}>
            <span>{p.nickname}</span>
            <span>{e('💬','댓글')} {p.comment_count}</span>
          </div>
        </div>
      )) : <div className="card"><div className="empty">아직 Pick이 없습니다</div></div>}
    </div>
  )
}

function AdminPage() {
  const [users, setUsers] = useState([])
  const [ips, setIps] = useState([])
  const [pending, setPending] = useState([])
  const [newIp, setNewIp] = useState({ ip: '', memo: '' })
  const [priceJson, setPriceJson] = useState('')
  const [priceDate, setPriceDate] = useState(new Date().toISOString().slice(0, 10))
  const [msg, setMsg] = useState('')
  const [stockJson, setStockJson] = useState('')
  // 포인트 관리
  const [pointAdjust, setPointAdjust] = useState({ user_id: '', amount: '', reason: '' })
  const [transactions, setTransactions] = useState({ transactions: [], total: 0, page: 1, pages: 0 })
  const [txFilter, setTxFilter] = useState({ user_id: '', source: '', page: 1 })
  const [diceRooms, setDiceRooms] = useState([])
  const [omokRooms, setOmokRooms] = useState([])
  const [chessRooms, setChessRooms] = useState([])
  const [settlement, setSettlement] = useState(null)

  const load = () => {
    api.adminGetUsers().then(setUsers).catch(() => {})
    api.adminGetIPs().then(setIps).catch(() => {})
    api.adminGetPendingStocks().then(setPending).catch(() => {})
    api.adminGetDiceRooms().then(setDiceRooms).catch(() => {})
    api.adminGetOmokRooms().then(setOmokRooms).catch(() => {})
    api.adminGetChessRooms().then(setChessRooms).catch(() => {})
    api.adminGetSettlementStatus().then(setSettlement).catch(() => {})
  }
  const loadTx = (filter) => {
    api.adminGetTransactions(filter || txFilter).then(setTransactions).catch(() => {})
  }
  useEffect(load, [])
  useEffect(() => { loadTx() }, [])

  const handleApprove = async (userId, approved) => {
    await api.adminApproveUser({ user_id: userId, approved })
    load()
  }

  const handleAddIP = async () => {
    if (!newIp.ip) return
    await api.adminAddIP(newIp)
    setNewIp({ ip: '', memo: '' }); load()
  }

  const handleRemoveIP = async (ip) => {
    await api.adminRemoveIP(ip); load()
  }

  const handlePriceInput = async () => {
    setMsg('')
    try {
      const parsed = JSON.parse(priceJson)
      // 지원 포맷: {"prices": {...}} 또는 {"005930": 58700, ...}
      const prices = parsed.prices || parsed
      const res = await api.adminInputPrices({ date: priceDate, prices })
      setMsg(`${e('✅','[OK]')}${res.message} | 종가 ${res.prices_count}개, 체결 ${res.settled_count}건`)
      setPriceJson('')
      load()
    } catch (err) { setMsg(`${e('❌','[ERR]')} ${err.message}`) }
  }

  const handleStockLoad = async () => {
    setMsg('')
    try {
      const stocks = JSON.parse(stockJson)
      const res = await api.adminLoadStocks({ stocks: Array.isArray(stocks) ? stocks : stocks.stocks })
      setMsg(`${e('✅','[OK]')}${res.message}`)
      setStockJson('')
    } catch (err) { setMsg(`${e('❌','[ERR]')} ${err.message}`) }
  }

  const handlePointAdjust = async () => {
    setMsg('')
    const uid = parseInt(pointAdjust.user_id)
    const amt = parseInt(pointAdjust.amount)
    if (!uid || !amt || !pointAdjust.reason) return setMsg(`${e('❌','[ERR]')} 유저 ID, 포인트, 사유를 모두 입력하세요`)
    try {
      const res = await api.adminAdjustPoints({ user_id: uid, amount: amt, reason: pointAdjust.reason })
      setMsg(`${e('✅','[OK]')}${res.message} (잔고: ${res.new_balance.toLocaleString()}P)`)
      setPointAdjust({ user_id: '', amount: '', reason: '' })
      loadTx()
    } catch (err) { setMsg(`${e('❌','[ERR]')} ${err.message}`) }
  }

  const handleDestroyDiceRoom = async (roomId) => {
    if (!confirm(`방 #${roomId}을 폭파하시겠습니까? 참가자들에게 참가비가 환불됩니다.`)) return
    try {
      const res = await api.adminDestroyDiceRoom(roomId)
      setMsg(`${e('✅','[OK]')}${res.message}`)
      load()
    } catch (err) { setMsg(`${e('❌','[ERR]')} ${err.message}`) }
  }

  const handleDestroyOmokRoom = async (roomId) => {
    if (!confirm(`오목 방 #${roomId}을 강제 종료하시겠습니까? 베팅금이 환불됩니다.`)) return
    try {
      const res = await api.adminDestroyOmokRoom(roomId)
      setMsg(`${e('✅','[OK]')}${res.message}`)
      load()
    } catch (err) { setMsg(`${e('❌','[ERR]')} ${err.message}`) }
  }

  const handleDestroyChessRoom = async (roomId) => {
    if (!confirm(`체스 방 #${roomId}을 강제 종료하시겠습니까? 베팅금이 환불됩니다.`)) return
    try {
      const res = await api.adminDestroyChessRoom(roomId)
      setMsg(`${e('✅','[OK]')}${res.message}`)
      load()
    } catch (err) { setMsg(`${e('❌','[ERR]')} ${err.message}`) }
  }

  const handleTxSearch = (e) => {
    e?.preventDefault()
    const f = { ...txFilter, page: 1 }
    setTxFilter(f)
    loadTx(f)
  }

  const handleTxPage = (p) => {
    const f = { ...txFilter, page: p }
    setTxFilter(f)
    loadTx(f)
  }

  return (
    <div>
      {/* 체결 입력 현황 */}
      {settlement && (
        <div className="card admin-section">
          <div className="card-title">{e('📅','')} 체결 입력 현황 ({settlement.month})</div>
          <div style={{display:'flex',gap:16,marginBottom:12,flexWrap:'wrap'}}>
            <span className="badge badge-green" style={{fontSize:13,padding:'4px 12px'}}>입력 완료: {settlement.entered_count}일</span>
            <span className={`badge ${settlement.missing_count > 0 ? 'badge-red' : 'badge-green'}`} style={{fontSize:13,padding:'4px 12px'}}>미입력: {settlement.missing_count}일</span>
            <span className="badge badge-blue" style={{fontSize:13,padding:'4px 12px'}}>전체 영업일: {settlement.total_business_days}일</span>
          </div>
          {settlement.missing_count > 0 && (
            <div style={{marginBottom:12,padding:12,background:'var(--danger-bg, rgba(255,59,48,0.1))',borderRadius:8,border:'1px solid var(--danger, #ff3b30)'}}>
              <div style={{fontSize:12,color:'var(--danger, #ff3b30)',fontWeight:600,marginBottom:6}}>미입력 날짜 ({settlement.missing_count}일):</div>
              <div style={{fontSize:13,lineHeight:1.8}}>
                {settlement.missing_dates.map(d => <span key={d} className="badge badge-red" style={{marginRight:4,marginBottom:4,cursor:'pointer'}} onClick={() => setPriceDate(d)}>{d}</span>)}
              </div>
            </div>
          )}
          {settlement.entered_count > 0 && (
            <div style={{padding:12,background:'var(--surface2)',borderRadius:8}}>
              <div style={{fontSize:12,color:'var(--text-dim)',marginBottom:6}}>입력 완료 날짜 ({settlement.entered_count}일):</div>
              <div style={{fontSize:13,lineHeight:1.8}}>
                {settlement.entered_dates.map(d => <span key={d} className="badge badge-green" style={{marginRight:4,marginBottom:4}}>{d}</span>)}
              </div>
            </div>
          )}
        </div>
      )}

      {/* 종가 입력 */}
      <div className="card admin-section">
        <div className="card-title">{e('📈','')} 종가 입력</div>
        {pending.length > 0 && (
          <div style={{marginBottom:12,padding:12,background:'var(--surface2)',borderRadius:8}}>
            <div style={{fontSize:12,color:'var(--text-dim)',marginBottom:6}}>업데이트 필요 종목 ({pending.length}개):</div>
            <div style={{fontSize:12,lineHeight:1.8}}>
              {pending.map(s => <span key={s.code} className="badge badge-blue" style={{marginRight:4,marginBottom:4}}>{s.name} ({s.code})</span>)}
            </div>
          </div>
        )}
        <div className="form-row">
          <div style={{maxWidth:200}}>
            <div className="form-label">날짜</div>
            <input type="date" value={priceDate} onChange={e => setPriceDate(e.target.value)} />
          </div>
        </div>
        <div className="form-group">
          <div className="form-label">종가 JSON</div>
          <textarea className="json-input" placeholder={'{"005930": 58700, "000660": 142500}'} value={priceJson}
            onChange={e => setPriceJson(e.target.value)} />
        </div>
        <button className="btn btn-primary" onClick={handlePriceInput}>종가 입력 & 체결</button>
        {msg && <div className="mt-8" style={{fontSize:13}}>{msg}</div>}
      </div>

      {/* 유저 관리 */}
      <div className="card admin-section">
        <div className="card-title">{e('👤','')} 유저 관리</div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>사번</th><th>닉네임</th><th>IP</th><th>상태</th><th></th></tr></thead>
            <tbody>
              {users.filter(u => !u.is_admin).map(u => (
                <tr key={u.id}>
                  <td className="mono">{u.employee_id}</td>
                  <td>{u.nickname}</td>
                  <td className="mono" style={{fontSize:11,color:'var(--text-dim)'}}>{u.ip_address || '-'}</td>
                  <td>{u.is_approved ? <span className="badge badge-green">승인</span> : <span className="badge badge-orange">대기</span>}</td>
                  <td className="text-right">
                    {u.is_approved
                      ? <button className="btn btn-danger btn-sm" onClick={() => handleApprove(u.id, false)}>차단</button>
                      : <button className="btn btn-success btn-sm" onClick={() => handleApprove(u.id, true)}>승인</button>
                    }
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* IP 관리 */}
      <div className="card admin-section">
        <div className="card-title">{e('🔒','')} IP 화이트리스트</div>
        <div className="form-row mb-16">
          <input placeholder="IP 주소" value={newIp.ip} onChange={e => setNewIp({...newIp, ip: e.target.value})} />
          <input placeholder="메모" value={newIp.memo} onChange={e => setNewIp({...newIp, memo: e.target.value})} />
          <button className="btn btn-primary" onClick={handleAddIP} style={{flex:'none'}}>추가</button>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>IP</th><th>메모</th><th>등록일</th><th></th></tr></thead>
            <tbody>
              {ips.map(ip => (
                <tr key={ip.ip}>
                  <td className="mono">{ip.ip}</td>
                  <td>{ip.memo}</td>
                  <td className="mono" style={{fontSize:11,color:'var(--text-dim)'}}>{ip.created_at}</td>
                  <td className="text-right"><button className="btn btn-danger btn-sm" onClick={() => handleRemoveIP(ip.ip)}>삭제</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 종목 로드 */}
      <div className="card admin-section">
        <div className="card-title">{e('📋','')} 종목 DB 로드</div>
        <div className="form-group">
          <div className="form-label">종목 JSON (배열)</div>
          <textarea className="json-input" rows={4}
            placeholder={'[{"code":"005930","name":"삼성전자","market":"KOSPI"}, ...]'}
            value={stockJson} onChange={e => setStockJson(e.target.value)} />
        </div>
        <button className="btn btn-primary" onClick={handleStockLoad}>종목 로드</button>
      </div>

      {/* 월간 리셋 */}
      <div className="card admin-section">
        <div className="card-title">{e('🔄','')} 월간 리셋</div>
        <p style={{fontSize:13,color:'var(--text-dim)',marginBottom:12}}>이번 달 시드를 1억으로 초기화하고 대기 주문을 모두 취소합니다.</p>
        <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
          <button className="btn btn-danger" onClick={async () => { if(confirm('순수 리셋: 포인트 보상 없이 리셋합니다. 진행하시겠습니까?')) { try { const r = await api.adminMonthReset(false); setMsg(`${e('✅','[OK]')} ${r.message}`) } catch(err) { setMsg(`${e('❌','[ERR]')} ${err.message}`) } } }}>순수 리셋</button>
          <button className="btn btn-primary" onClick={async () => { if(confirm('랭킹 보상 후 리셋: 1등 +5000P / 2등 +3000P / 3등 +1000P / 꼴등 -500P 적용 후 리셋합니다. 진행하시겠습니까?')) { try { const r = await api.adminMonthReset(true); setMsg(`${e('✅','[OK]')} ${r.message}`) } catch(err) { setMsg(`${e('❌','[ERR]')} ${err.message}`) } } }}>랭킹 보상 + 리셋</button>
        </div>
      </div>

      {/* 전체 포인트 초기화 */}
      <div className="card admin-section">
        <div className="card-title">{e('💰','')} 전체 포인트 초기화</div>
        <p style={{fontSize:13,color:'var(--text-dim)',marginBottom:12}}>모든 유저의 포인트를 10,000P로 초기화합니다.</p>
        <button className="btn btn-danger" onClick={async () => { if(confirm('전체 유저의 포인트를 10,000P로 초기화합니다. 정말 진행하시겠습니까?')) { try { const r = await api.adminResetAllPoints(); setMsg(`${e('✅','[OK]')} ${r.message}`) } catch(err) { setMsg(`${e('❌','[ERR]')} ${err.message}`) } } }}>전체 포인트 10,000P 초기화</button>
      </div>

      {/* 주간 보상 */}
      <div className="card admin-section">
        <div className="card-title">{e('🏆','')} 주간 보상 지급</div>
        <p style={{fontSize:13,color:'var(--text-dim)',marginBottom:12}}>오목 MMR 상위 3명, 노들 주간 상위 3명에게 보상을 지급합니다. (1등 3,000P / 2등 2,000P / 3등 1,000P)</p>
        <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
          <button className="btn btn-primary" onClick={async () => { try { const r = await api.adminGiveWeeklyRewards('all'); setMsg(`${e('✅','[OK]')} ${r.message}`) } catch(err) { setMsg(`${e('❌','[ERR]')} ${err.message}`) } }}>전체 주간 보상</button>
          <button className="btn btn-ghost" onClick={async () => { try { const r = await api.adminGiveWeeklyRewards('omok'); setMsg(`${e('✅','[OK]')} ${r.message}`) } catch(err) { setMsg(`${e('❌','[ERR]')} ${err.message}`) } }}>오목만</button>
          <button className="btn btn-ghost" onClick={async () => { try { const r = await api.adminGiveWeeklyRewards('nordle'); setMsg(`${e('✅','[OK]')} ${r.message}`) } catch(err) { setMsg(`${e('❌','[ERR]')} ${err.message}`) } }}>노들만</button>
        </div>
      </div>

      {/* 채팅 관리 */}
      <div className="card admin-section">
        <div className="card-title">{e('💬','')} 채팅 관리</div>
        <button className="btn btn-danger" onClick={async () => { if(confirm('채팅 내역을 전부 초기화합니다. 진행하시겠습니까?')) { try { const r = await api.adminClearChat(); setMsg(`${e('✅','[OK]')} ${r.message}`) } catch(err) { setMsg(`${e('❌','[ERR]')} ${err.message}`) } } }}>채팅 전체 초기화</button>
      </div>

      {/* 오목 방 관리 */}
      <div className="card admin-section">
        <div className="card-title">{e('⚫','')} 오목 방 관리</div>
        {omokRooms.length === 0 ? (
          <p style={{fontSize:13,color:'var(--text-dim)'}}>진행 중인 방이 없습니다.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>#</th><th>방장</th><th>상대</th><th>베팅</th><th>수</th><th>상태</th><th></th></tr></thead>
              <tbody>
                {omokRooms.map(r => (
                  <tr key={r.id}>
                    <td className="mono">{r.id}</td>
                    <td>{r.creator_name}</td>
                    <td>{r.opponent_name || <span style={{color:'var(--text-dim)'}}>대기중</span>}</td>
                    <td className="mono">{r.bet_amount.toLocaleString()}P</td>
                    <td className="text-center">{r.move_count}</td>
                    <td><span className={`badge ${r.status === 'PLAYING' ? 'badge-orange' : 'badge-green'}`}>{r.status === 'PLAYING' ? '진행중' : '대기중'}</span></td>
                    <td className="text-right">
                      <button className="btn btn-danger btn-sm" onClick={() => handleDestroyOmokRoom(r.id)}>강제종료</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 체스 방 관리 */}
      <div className="card admin-section">
        <div className="card-title">{e('♟','')} 체스 방 관리</div>
        {chessRooms.length === 0 ? (
          <p style={{fontSize:13,color:'var(--text-dim)'}}>진행 중인 방이 없습니다.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>#</th><th>방장</th><th>상대</th><th>베팅</th><th>수</th><th>상태</th><th></th></tr></thead>
              <tbody>
                {chessRooms.map(r => (
                  <tr key={r.id}>
                    <td className="mono">{r.id}</td>
                    <td>{r.creator_name}</td>
                    <td>{r.opponent_name || <span style={{color:'var(--text-dim)'}}>대기중</span>}</td>
                    <td className="mono">{r.bet_amount.toLocaleString()}P</td>
                    <td className="text-center">{r.move_count}</td>
                    <td><span className={`badge ${r.status === 'PLAYING' ? 'badge-orange' : 'badge-green'}`}>{r.status === 'PLAYING' ? '진행중' : '대기중'}</span></td>
                    <td className="text-right">
                      <button className="btn btn-danger btn-sm" onClick={() => handleDestroyChessRoom(r.id)}>강제종료</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 주사위 방 관리 */}
      <div className="card admin-section">
        <div className="card-title">{e('🎲','')} 주사위 방 관리</div>
        {diceRooms.length === 0 ? (
          <p style={{fontSize:13,color:'var(--text-dim)'}}>진행 중인 방이 없습니다.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>#</th><th>방장</th><th>모드</th><th>참가비</th><th>인원</th><th>상태</th><th></th></tr></thead>
              <tbody>
                {diceRooms.map(r => (
                  <tr key={r.id}>
                    <td className="mono">{r.id}</td>
                    <td>{r.creator_name}</td>
                    <td><span className="badge badge-blue">{r.mode}</span></td>
                    <td className="mono">{r.entry_fee.toLocaleString()}P</td>
                    <td className="text-center">{r.player_count}명</td>
                    <td><span className={`badge ${r.status === 'ROLLING' ? 'badge-orange' : 'badge-green'}`}>{r.status === 'ROLLING' ? '진행중' : '대기중'}</span></td>
                    <td className="text-right">
                      <button className="btn btn-danger btn-sm" onClick={() => handleDestroyDiceRoom(r.id)}>폭파</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 포인트 수동 조정 */}
      <div className="card admin-section">
        <div className="card-title">{e('💰','')} 포인트 수동 조정</div>
        <p style={{fontSize:13,color:'var(--text-dim)',marginBottom:12}}>특정 유저의 포인트를 지급하거나 차감합니다. (양수=지급, 음수=차감)</p>
        <div className="form-row mb-16" style={{gap:8,flexWrap:'wrap'}}>
          <select value={pointAdjust.user_id} onChange={e => setPointAdjust({...pointAdjust, user_id: e.target.value})}
            style={{minWidth:160}}>
            <option value="">유저 선택</option>
            {users.filter(u => !u.is_admin).map(u => (
              <option key={u.id} value={u.id}>{u.nickname} ({u.employee_id})</option>
            ))}
          </select>
          <input type="number" placeholder="포인트 (예: 500, -200)" value={pointAdjust.amount}
            onChange={e => setPointAdjust({...pointAdjust, amount: e.target.value})} style={{maxWidth:160}} />
          <input placeholder="사유" value={pointAdjust.reason}
            onChange={e => setPointAdjust({...pointAdjust, reason: e.target.value})} style={{flex:1,minWidth:150}} />
          <button className="btn btn-primary" onClick={handlePointAdjust} style={{flex:'none'}}>적용</button>
        </div>
      </div>

      {/* 포인트 가감 내역 */}
      <div className="card admin-section">
        <div className="card-title">{e('📋','')} 포인트 가감 내역</div>
        <form onSubmit={handleTxSearch} className="form-row mb-16" style={{gap:8,flexWrap:'wrap'}}>
          <select value={txFilter.user_id} onChange={e => setTxFilter({...txFilter, user_id: e.target.value})}
            style={{minWidth:140}}>
            <option value="">전체 유저</option>
            {users.filter(u => !u.is_admin).map(u => (
              <option key={u.id} value={u.id}>{u.nickname}</option>
            ))}
          </select>
          <input placeholder="소스 검색 (출석, 베팅, 관리자...)" value={txFilter.source}
            onChange={e => setTxFilter({...txFilter, source: e.target.value})} style={{flex:1,minWidth:120}} />
          <button type="submit" className="btn btn-primary" style={{flex:'none'}}>검색</button>
        </form>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>시간</th><th>유저</th><th>변동</th><th>잔고</th><th>소스</th><th>설명</th></tr>
            </thead>
            <tbody>
              {transactions.transactions.map(t => (
                <tr key={t.id}>
                  <td className="mono" style={{fontSize:11,color:'var(--text-dim)',whiteSpace:'nowrap'}}>{t.created_at}</td>
                  <td>{t.nickname}</td>
                  <td style={{fontWeight:600,color: t.amount > 0 ? 'var(--green)' : 'var(--red)'}}>
                    {t.amount > 0 ? '+' : ''}{t.amount.toLocaleString()}P
                  </td>
                  <td className="mono">{t.balance_after.toLocaleString()}P</td>
                  <td><span className="badge badge-blue">{t.source}</span></td>
                  <td style={{fontSize:12,color:'var(--text-dim)'}}>{t.description || '-'}</td>
                </tr>
              ))}
              {transactions.transactions.length === 0 && (
                <tr><td colSpan={6} style={{textAlign:'center',color:'var(--text-dim)'}}>내역이 없습니다</td></tr>
              )}
            </tbody>
          </table>
        </div>
        {transactions.pages > 1 && (
          <div style={{display:'flex',justifyContent:'center',gap:4,marginTop:12}}>
            {Array.from({length: Math.min(transactions.pages, 10)}, (_, i) => {
              const p = i + 1
              return <button key={p} className={`btn btn-sm ${p === transactions.page ? 'btn-primary' : ''}`}
                onClick={() => handleTxPage(p)}>{p}</button>
            })}
            {transactions.pages > 10 && <span style={{color:'var(--text-dim)',alignSelf:'center'}}>... ({transactions.pages})</span>}
          </div>
        )}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════
// RPS PAGE (가위바위보)
// ═══════════════════════════════════════════════
const RPS_LABELS = () => ({ rock: `바위 ${e('✊','[바위]')}`, paper: `보 ${e('✋','[보]')}`, scissors: `가위 ${e('✌️','[가위]')}` })
const RPS_EMOJI = () => ({ rock: e('✊','[바위]'), paper: e('✋','[보]'), scissors: e('✌️','[가위]') })

function RPSPage({ onPointsChange }) {
  const [points, setPoints] = useState(0)
  const [wager, setWager] = useState('')
  const [result, setResult] = useState(null)
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(true)
  const [playing, setPlaying] = useState(false)
  const [status, setStatus] = useState(null)
  const [showHelp, setShowHelp] = useState(false)

  const load = () => {
    setLoading(true)
    Promise.all([
      api.getPoints().catch(() => ({ points: 0 })),
      api.getRPSHistory().catch(() => []),
      api.getRPSStatus().catch(() => null),
    ]).then(([p, h, s]) => {
      setPoints(p.points)
      setHistory(h)
      setStatus(s)
      setLoading(false)
    })
  }
  useEffect(load, [])

  const play = async (choice) => {
    const w = parseInt(wager)
    if (!w || w <= 0) return alert('배팅 포인트를 입력하세요')
    if (w > points) return alert('포인트가 부족합니다')
    const maxWager = Math.max(1, Math.floor(points * 0.9))
    if (w > maxWager) return alert(`보유 포인트의 90%까지만 배팅할 수 있습니다 (최대 ${maxWager.toLocaleString()}P)`)
    setPlaying(true)
    try {
      const res = await api.playRPS({ choice, wager: w })
      setResult(res)
      setPoints(res.new_balance)
      setStatus(prev => prev ? { ...prev, jackpot_pool: res.jackpot_pool } : prev)
      onPointsChange?.()
      api.getRPSHistory().then(setHistory).catch(() => {})
    } catch (err) {
      alert(err.message)
    }
    setPlaying(false)
  }

  if (loading) return <div className="loading">로딩 중...</div>

  return (
    <div>
      <div className="card mb-16">
        <div className="flex-between mb-16">
          <div style={{display:'flex',alignItems:'center',gap:8}}>
            <div className="card-title" style={{margin:0}}>가위바위보</div>
            <button className="rps-help-btn" onClick={() => setShowHelp(!showHelp)} title="게임 규칙">?</button>
          </div>
          <span className="badge badge-orange" style={{fontSize:13,padding:'4px 12px'}}>{e('🎲','[P]')} {fmt(points)} P</span>
        </div>

        {/* 상태 배너: 잭팟 */}
        <div className="rps-status-bar">
          <div className="rps-jackpot">
            {e('🎰','')} 잭팟 풀: <strong>{fmt(status?.jackpot_pool || 0)}P</strong>
          </div>
        </div>

        {/* 도움말 팝업 */}
        {showHelp && (
          <div className="rps-help-popup">
            <div className="rps-help-section">
              <strong>기본 규칙</strong>
              <p>배당 1.98배 (승리 시 배팅금의 98% 수익). 배팅금의 5%는 잭팟 풀에 적립.</p>
            </div>
            <div className="rps-help-section">
              <strong>{e('🎰','')} 잭팟</strong>
              <p>모든 배팅금의 5%가 잭팟 풀에 쌓임. 100P 이상 배팅 시 0.1% 확률로 당첨 (승패 무관).</p>
            </div>
          </div>
        )}

        <div className="form-group">
          <div className="form-label">배팅 포인트 <span style={{fontSize:11,color:'var(--text-dim)'}}>(최대 {fmt(Math.max(1, Math.floor(points * 0.9)))}P · 배당 1.98배)</span></div>
          <input type="number" placeholder="걸 포인트 입력" value={wager}
            onChange={e => setWager(e.target.value)} max={Math.max(1, Math.floor(points * 0.9))} style={{maxWidth:200}} />
        </div>

        <div className="rps-choices">
          {['scissors', 'rock', 'paper'].map(c => (
            <button key={c} className="rps-choice" onClick={() => play(c)} disabled={playing}>
              {!isExcel() && <span className="rps-emoji">{RPS_EMOJI()[c]}</span>}
              <span className="rps-label">{c === 'rock' ? '바위' : c === 'paper' ? '보' : '가위'}</span>
            </button>
          ))}
        </div>

        {result && (
          <div className={`rps-result mt-16 ${result.jackpot_win > 0 && !isExcel() ? 'rps-jackpot-glow' : ''}`}>
            {/* 잭팟 당첨 */}
            {result.jackpot_win > 0 && !isExcel() && (
              <div className="rps-jackpot-banner">
                {e('🎰','')} JACKPOT! +{fmt(result.jackpot_win)}P {e('🎰','')}
              </div>
            )}
            <div className="rps-battle">
              <div className="rps-side">
                <div style={{fontSize:11,color:'var(--text-dim)',marginBottom:4}}>나</div>
                <span style={{fontSize:40}}>{RPS_EMOJI()[result.player_choice]}</span>
              </div>
              <span style={{fontSize:18,color:'var(--text-dim)',alignSelf:'center'}}>VS</span>
              <div className="rps-side">
                <div style={{fontSize:11,color:'var(--text-dim)',marginBottom:4}}>컴퓨터</div>
                <span style={{fontSize:40}}>{RPS_EMOJI()[result.computer_choice]}</span>
              </div>
            </div>
            <div style={{textAlign:'center',marginTop:12}}>
              <span className={`badge ${result.result === 'win' ? 'badge-green' : result.result === 'lose' ? 'badge-red' : 'badge-orange'}`}
                style={{fontSize:14,padding:'6px 16px'}}>
                {result.result === 'win'
                  ? `승리! +${fmt(result.payout)}P${result.happy_bonus > 0 ? ` (해피 +${fmt(result.happy_bonus)})` : ''}`
                  : result.result === 'lose' ? `패배 ${fmt(result.payout)}P` : '무승부'}
              </span>
            </div>
          </div>
        )}
      </div>

      {history.length > 0 && (
        <div className="card">
          <div className="card-title">최근 기록</div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>시간</th><th className="text-center">나</th><th className="text-center">상대</th><th className="text-center">결과</th><th className="text-right">배팅</th><th className="text-right">수익</th></tr></thead>
              <tbody>
                {history.map(g => (
                  <tr key={g.id}>
                    <td style={{fontSize:11,color:'var(--text-dim)'}}>{g.created_at}</td>
                    <td className="text-center">{RPS_EMOJI()[g.player_choice]}</td>
                    <td className="text-center">{RPS_EMOJI()[g.computer_choice]}</td>
                    <td className="text-center">
                      <span className={`badge ${g.result === 'win' ? 'badge-green' : g.result === 'lose' ? 'badge-red' : 'badge-orange'}`}>
                        {g.result === 'win' ? '승' : g.result === 'lose' ? '패' : '무'}
                      </span>
                    </td>
                    <td className="text-right mono">{fmt(g.wager)}</td>
                    <td className={`text-right mono ${g.payout > 0 ? 'profit-positive' : g.payout < 0 ? 'profit-negative' : ''}`}>
                      {g.payout > 0 ? '+' : ''}{fmt(g.payout)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}


// ═══════════════════════════════════════════════
// DICE PAGE (주사위 게임)
// ═══════════════════════════════════════════════
function DicePage({ onPointsChange }) {
  const [view, setView] = useState('list') // list | room
  const [rooms, setRooms] = useState([])
  const [room, setRoom] = useState(null)
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(true)
  const [points, setPoints] = useState(0)
  const [showCreate, setShowCreate] = useState(false)
  const [createForm, setCreateForm] = useState({ mode: 'HIGH', dice_min: 1, dice_max: 6, entry_fee: '' })
  const [showHistory, setShowHistory] = useState(false)
  const [rolling, setRolling] = useState(false)
  const pollingRef = useRef(null)
  const currentUser = api.getUser()

  const loadRooms = async () => {
    try {
      const [rs, p] = await Promise.all([
        api.getDiceRooms().catch(() => []),
        api.getPoints().catch(() => ({ points: 0 })),
      ])
      setRooms(rs)
      setPoints(p.points)
    } catch {}
    setLoading(false)
  }

  const loadRoom = async (id) => {
    try {
      const r = await api.getDiceRoom(id)
      setRoom(r)
      if (r.status === 'CANCELLED') {
        stopPolling()
      }
    } catch (e) {
      alert(e.message)
      goBack()
    }
  }

  const startPolling = (id) => {
    stopPolling()
    pollingRef.current = setInterval(() => loadRoom(id), 2000)
  }

  const stopPolling = () => {
    if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null }
  }

  const goBack = () => {
    stopPolling()
    setView('list')
    setRoom(null)
    loadRooms()
    onPointsChange?.()
  }

  useEffect(() => {
    loadRooms()
    return () => stopPolling()
  }, [])

  const enterRoom = async (id) => {
    setLoading(true)
    try {
      const r = await api.getDiceRoom(id)
      setRoom(r)
      setView('room')
      startPolling(id)
    } catch (e) { alert(e.message) }
    setLoading(false)
  }

  const handleCreate = async () => {
    const fee = parseInt(createForm.entry_fee)
    if (!fee || fee < 10) return alert('최소 참가비는 10P입니다')
    if (createForm.dice_min >= createForm.dice_max) return alert('주사위 범위가 올바르지 않습니다')
    try {
      const res = await api.createDiceRoom({ ...createForm, entry_fee: fee })
      setShowCreate(false)
      setCreateForm({ mode: 'HIGH', dice_min: 1, dice_max: 6, entry_fee: '' })
      enterRoom(res.room_id)
      onPointsChange?.()
    } catch (e) { alert(e.message) }
  }

  const handleJoin = async (id) => {
    try {
      await api.joinDiceRoom(id)
      enterRoom(id)
      onPointsChange?.()
    } catch (e) { alert(e.message) }
  }

  const handleReady = async () => {
    try {
      await api.toggleDiceReady(room.id)
      loadRoom(room.id)
    } catch (e) { alert(e.message) }
  }

  const handleStartRound = async () => {
    try {
      await api.startDiceRound(room.id)
      loadRoom(room.id)
    } catch (e) { alert(e.message) }
  }

  const handleRoll = async () => {
    setRolling(true)
    try {
      const res = await api.rollDice(room.id)
      loadRoom(room.id)
      if (res.finished) onPointsChange?.()
    } catch (e) { alert(e.message) }
    setRolling(false)
  }

  const handleCancel = async () => {
    if (!confirm('방을 끝내시겠습니까? 참가비가 환불됩니다.')) return
    try {
      await api.cancelDiceRoom(room.id)
      goBack()
    } catch (e) { alert(e.message) }
  }

  const handleLeave = async () => {
    if (!confirm('방에서 나가시겠습니까? 참가비가 환불됩니다.')) return
    try {
      await api.leaveDiceRoom(room.id)
      goBack()
    } catch (e) { alert(e.message) }
  }

  const handleNextGame = async () => {
    try {
      await api.nextDiceGame(room.id)
      loadRoom(room.id)
      onPointsChange?.()
    } catch (e) { alert(e.message) }
  }

  const loadHistory = async () => {
    try {
      const h = await api.getDiceHistory()
      setHistory(h)
      setShowHistory(true)
    } catch (e) { alert(e.message) }
  }

  if (loading) return <div className="loading">로딩 중...</div>

  // ── Room View ──
  if (view === 'room' && room) {
    const isCreator = currentUser?.user_id === room.creator_id
    const myPlayer = room.players?.find(p => p.user_id === currentUser?.user_id)
    const isParticipant = !!myPlayer
    const alivePlayers = room.players?.filter(p => p.is_alive) || []
    const myRoll = room.current_rolls?.find(r => r.user_id === currentUser?.user_id)
    const allReady = room.players?.every(p => p.is_ready)
    const roundResult = room.round_result // 'WIN' | 'DRAW' | null
    const winnerPlayer = room.winner_id ? room.players?.find(p => p.user_id === room.winner_id) : null

    return (
      <div>
        <button className="btn btn-outline mb-16" onClick={goBack} style={{fontSize:12}}>← 목록으로</button>

        {/* 방 정보 헤더 */}
        <div className="card mb-16">
          <div className="flex-between mb-8">
            <div className="card-title" style={{margin:0}}>
              {room.mode === 'HIGH' ? `${e('🔺','▲')} HIGH` : `${e('🔻','▼')} LOW`} 모드
            </div>
            <span className={`badge ${room.status === 'ROLLING' ? 'badge-green' : room.status === 'CANCELLED' ? 'badge-red' : 'badge-orange'}`}>
              {room.status === 'ROLLING' ? '진행중' : room.status === 'CANCELLED' ? '취소됨'
                : roundResult === 'WIN' ? '승자 결정' : roundResult === 'DRAW' ? '무승부' : '대기중'}
            </span>
          </div>
          <div style={{display:'flex',gap:16,flexWrap:'wrap',fontSize:13,color:'var(--text-dim)'}}>
            <span>방장: {room.creator_name}</span>
            <span>참가비: {fmt(room.entry_fee)}P / 라운드</span>
            <span>판돈: <strong style={{color:'var(--accent-orange)'}}>{fmt(room.total_pot)}P</strong></span>
            <span>주사위: {room.dice_min}~{room.dice_max}</span>
            {room.current_round > 0 && <span>라운드: {room.current_round}</span>}
          </div>
        </div>

        {/* 참가자 목록 */}
        <div className="card mb-16">
          <div className="card-title">참가자 ({room.players?.length || 0}명)</div>
          <div className="dice-players">
            {room.players?.map(p => {
              const roll = room.current_rolls?.find(r => r.user_id === p.user_id)
              return (
                <div key={p.user_id} className={`dice-player ${!p.is_alive && room.current_round > 0 ? 'eliminated' : ''}`}>
                  <span className="dice-player-name">
                    {p.nickname}
                    {p.user_id === room.creator_id && <span style={{fontSize:10,color:'var(--text-dim)',marginLeft:4}}>(방장)</span>}
                  </span>
                  {/* 대기중: 준비 상태 */}
                  {room.status === 'WAITING' && room.current_round === 0 && (
                    <span className={`badge ${p.is_ready ? 'badge-green' : 'badge-red'}`} style={{fontSize:10}}>
                      {p.is_ready ? '준비완료' : '대기중'}
                    </span>
                  )}
                  {/* 진행중: 굴림 상태 */}
                  {room.status === 'ROLLING' && p.is_alive && (
                    (() => {
                      if (!roll) return <span className="badge badge-orange" style={{fontSize:10}}>굴리는 중...</span>
                      if (room.all_rolled) return (
                        <span className={`dice-roll-value ${roll.eliminated ? 'eliminated' : ''}`}>
                          {e('🎲','#')}{roll.roll_value} {roll.eliminated ? e('💀','[탈락]') : ''}
                        </span>
                      )
                      if (p.user_id === currentUser?.user_id) return <span className="dice-roll-value">{e('🎲','#')}{roll.roll_value}</span>
                      return <span className="badge badge-orange" style={{fontSize:10}}>완료</span>
                    })()
                  )}
                  {/* 라운드 결과 확정 후 */}
                  {room.status === 'WAITING' && room.current_round > 0 && roundResult !== 'REROLL' && roll && (
                    <span className="dice-roll-value" style={{display:'inline-flex',alignItems:'center',gap:6}}>
                      {e('🎲','#')}{roll.roll_value}
                      {roll.eliminated ? <span style={{color:'var(--accent-red)'}}>{e('💀','[탈락]')}</span> : ''}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* ── 대기중: 첫 게임 시작 전 ── */}
        {room.status === 'WAITING' && room.current_round === 0 && isParticipant && (
          <div className="card mb-16">
            <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
              {!isCreator && (
                <>
                  <button className={`btn ${myPlayer?.is_ready ? 'btn-outline' : 'btn-green'}`} onClick={handleReady}>
                    {myPlayer?.is_ready ? '준비 취소' : '준비 완료'}
                  </button>
                  <button className="btn btn-outline" onClick={handleLeave} style={{color:'var(--accent-red)'}}>나가기</button>
                </>
              )}
              {isCreator && (
                <>
                  <button className="btn btn-primary" onClick={handleStartRound}
                    disabled={!allReady || room.players.length < 2}>
                    {e('🎲','')} 게임 시작
                  </button>
                  <button className="btn btn-outline" onClick={handleCancel} style={{color:'var(--accent-red)'}}>방 끝내기</button>
                </>
              )}
            </div>
          </div>
        )}

        {/* ── 진행중: 주사위 굴리기 ── */}
        {room.status === 'ROLLING' && isCreator && (
          <div style={{textAlign:'right',marginBottom:8}}>
            <button className="btn btn-outline" onClick={handleCancel} style={{fontSize:11,color:'var(--accent-red)'}}>방 끝내기</button>
          </div>
        )}

        {room.status === 'ROLLING' && isParticipant && myPlayer?.is_alive && !myRoll && (
          <div className="card mb-16 dice-roll-action">
            <div className="card-title" style={{margin:'0 0 12px'}}>주사위를 굴리세요!</div>
            <button className="btn btn-primary dice-roll-btn" onClick={handleRoll} disabled={rolling}>
              {rolling ? '굴리는 중...' : `${e('🎲','')} 주사위 굴리기`}
            </button>
          </div>
        )}

        {room.status === 'ROLLING' && myRoll && !room.all_rolled && (
          <div className="card mb-16" style={{textAlign:'center'}}>
            <div style={{fontSize:13,color:'var(--text-dim)',marginBottom:8}}>내 주사위: <strong style={{fontSize:20}}>{myRoll.roll_value}</strong></div>
            <div style={{fontSize:12,color:'var(--text-dim)'}}>다른 참가자를 기다리는 중...</div>
          </div>
        )}

        {/* ── 라운드 결과: 승자 확정 ── */}
        {roundResult === 'WIN' && (() => {
          const sortedRolls = [...(room.current_rolls || [])].sort((a, b) =>
            room.mode === 'HIGH' ? b.roll_value - a.roll_value : a.roll_value - b.roll_value
          )
          return (
            <div className="card mb-16 dice-winner-card">
              <div style={{textAlign:'center',marginBottom:16}}>
                <div style={{fontSize:40,marginBottom:8}}>{e('🏆','[우승]')}</div>
                <div style={{fontSize:18,fontWeight:700,marginBottom:2}}>{winnerPlayer?.nickname} 우승!</div>
                <div style={{fontSize:13,color:'var(--text-dim)'}}>
                  동수 탈락 → {room.mode === 'HIGH' ? '최고값' : '최저값'} 승리
                </div>
              </div>
              {/* 주사위 결과 + 포인트 변동 */}
              <div style={{borderTop:'1px solid rgba(255,255,255,0.15)',paddingTop:12}}>
                {sortedRolls.map(r => {
                  const isWinner = r.user_id === room.winner_id
                  const change = isWinner ? room.total_pot - room.entry_fee : -room.entry_fee
                  const label = r.eliminated ? '동수 탈락' : isWinner ? '승리' : '패배'
                  return (
                    <div key={r.user_id} style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'6px 0',borderBottom:'1px solid rgba(255,255,255,0.08)',fontSize:13}}>
                      <span style={{opacity: isWinner ? 1 : 0.6}}>
                        {isWinner ? e('🏆','[우승]') : r.eliminated ? e('💀','[탈락]') : e('😢','[패배]')} {r.nickname}
                        <span style={{color:'var(--text-dim)',marginLeft:6,fontSize:11}}>({label})</span>
                      </span>
                      <span style={{display:'flex',alignItems:'center',gap:10}}>
                        <span style={{fontFamily:'var(--font-mono)',fontSize:15}}>{r.roll_value}</span>
                        <span style={{fontWeight:700,fontFamily:'var(--font-mono)',minWidth:70,textAlign:'right',
                          color: isWinner ? 'var(--accent-green)' : 'var(--accent-red)'}}>
                          {change > 0 ? '+' : ''}{fmt(change)}P
                        </span>
                      </span>
                    </div>
                  )
                })}
              </div>
              {/* 방장 액션 */}
              {isCreator && (
                <div style={{display:'flex',gap:8,justifyContent:'center',marginTop:16}}>
                  <button className="btn btn-primary" onClick={handleNextGame}>{e('🎲','')} 한 판 더 ({fmt(room.entry_fee)}P)</button>
                  <button className="btn btn-outline" onClick={handleCancel} style={{color:'var(--accent-red)'}}>방 끝내기</button>
                </div>
              )}
              {!isCreator && (
                <div style={{textAlign:'center',marginTop:12,fontSize:12,color:'var(--text-dim)'}}>
                  방장이 '한 판 더' 또는 '방 끝내기'를 선택합니다
                </div>
              )}
            </div>
          )
        })()}

        {/* ── 라운드 결과: 무승부 ── */}
        {roundResult === 'DRAW' && (
          <div className="card mb-16" style={{padding:24}}>
            <div style={{textAlign:'center',marginBottom:12}}>
              <div style={{fontSize:36,marginBottom:8}}>{e('🤝','[무승부]')}</div>
              <div style={{fontSize:18,fontWeight:700,marginBottom:4}}>무승부!</div>
              <div style={{color:'var(--text-dim)',fontSize:13}}>전원 동수 탈락 — 참가비 환불 완료</div>
            </div>
            <div style={{borderTop:'1px solid var(--border)',paddingTop:12}}>
              {room.current_rolls?.map(r => (
                <div key={r.user_id} style={{display:'flex',justifyContent:'space-between',padding:'5px 0',fontSize:13}}>
                  <span>{e('💀','[탈락]')} {r.nickname}</span>
                  <span style={{display:'flex',alignItems:'center',gap:10}}>
                    <span style={{fontFamily:'var(--font-mono)',fontSize:15}}>{r.roll_value}</span>
                    <span style={{fontWeight:700,fontFamily:'var(--font-mono)',color:'var(--text-dim)'}}>±0P</span>
                  </span>
                </div>
              ))}
            </div>
            {isCreator && (
              <div style={{display:'flex',gap:8,justifyContent:'center',marginTop:16}}>
                <button className="btn btn-primary" onClick={handleNextGame}>{e('🎲','')} 한 판 더 ({fmt(room.entry_fee)}P)</button>
                <button className="btn btn-outline" onClick={handleCancel} style={{color:'var(--accent-red)'}}>방 끝내기</button>
              </div>
            )}
            {!isCreator && (
              <div style={{textAlign:'center',fontSize:12,color:'var(--text-dim)',marginTop:8}}>
                방장이 '한 판 더' 또는 '방 끝내기'를 선택합니다
              </div>
            )}
          </div>
        )}

        {/* 라운드 결과 상세 (진행중 전원 완료 시) */}
        {room.status === 'ROLLING' && room.all_rolled && room.current_rolls?.length > 0 && (
          <div className="card mb-16">
            <div className="card-title">라운드 {room.current_round} 결과</div>
            {room.current_rolls?.sort((a, b) => b.roll_value - a.roll_value)?.map(r => (
              <div key={r.user_id} style={{display:'flex',justifyContent:'space-between',padding:'5px 0',borderBottom:'1px solid var(--border)',fontSize:13}}>
                <span>{r.nickname}</span>
                <span>{e('🎲','#')}{r.roll_value} {r.eliminated ? <span style={{color:'var(--accent-red)'}}>{e('💀','[탈락]')}</span> : ''}</span>
              </div>
            ))}
          </div>
        )}

        {/* 방 취소됨 */}
        {room.status === 'CANCELLED' && (
          <div className="card mb-16" style={{textAlign:'center',padding:24}}>
            <div style={{fontSize:30,marginBottom:8}}>{e('🚫','[종료]')}</div>
            <div style={{fontSize:16,fontWeight:600,marginBottom:4}}>방이 종료되었습니다</div>
            <div style={{color:'var(--text-dim)',fontSize:13,marginBottom:12}}>참가비가 환불됩니다</div>
            <button className="btn btn-outline" onClick={goBack} style={{fontSize:12}}>목록으로</button>
          </div>
        )}

        {/* 이전 라운드 기록 */}
        {room.previous_rounds?.length > 0 && (
          <div className="card">
            <div className="card-title">이전 라운드 기록</div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>R</th><th>닉네임</th><th className="text-center">주사위</th><th className="text-center">결과</th></tr></thead>
                <tbody>
                  {room.previous_rounds.map((r, i) => (
                    <tr key={i}>
                      <td>{r.round_number}</td>
                      <td>{r.nickname}</td>
                      <td className="text-center mono">{r.roll_value}</td>
                      <td className="text-center">
                        {r.eliminated ? <span className="badge badge-red">탈락</span> : <span className="badge badge-green">생존</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    )
  }

  // ── List View ──
  return (
    <div>
      <div className="flex-between mb-16">
        <div style={{display:'flex',gap:8,alignItems:'center'}}>
          <span className="badge badge-orange" style={{fontSize:13,padding:'4px 12px'}}>{e('🎲','[P]')} {fmt(points)} P</span>
        </div>
        <div style={{display:'flex',gap:8}}>
          <button className="btn btn-outline" onClick={loadHistory} style={{fontSize:12}}>{e('📜','')} 기록</button>
          <button className="btn btn-primary" onClick={() => setShowCreate(!showCreate)} style={{fontSize:12}}>
            {showCreate ? '취소' : '+ 방 만들기'}
          </button>
        </div>
      </div>

      {showCreate && (
        <div className="card mb-16">
          <div className="card-title">새 게임방</div>
          <div style={{fontSize:12,color:'var(--text-dim)',marginBottom:12}}>
            규칙: 동수 전원 탈락 → 생존자 중 HIGH면 최고값, LOW면 최저값이 승자!
          </div>
          <div className="form-group">
            <div className="form-label">모드</div>
            <div style={{display:'flex',gap:8}}>
              <button className={`btn ${createForm.mode === 'HIGH' ? 'btn-primary' : 'btn-outline'}`}
                onClick={() => setCreateForm({...createForm, mode: 'HIGH'})}>{e('🔺','▲')} HIGH (높은 수 승리)</button>
              <button className={`btn ${createForm.mode === 'LOW' ? 'btn-primary' : 'btn-outline'}`}
                onClick={() => setCreateForm({...createForm, mode: 'LOW'})}>{e('🔻','▼')} LOW (낮은 수 승리)</button>
            </div>
          </div>
          <div style={{display:'flex',gap:12}}>
            <div className="form-group" style={{flex:1}}>
              <div className="form-label">최소값</div>
              <input type="number" value={createForm.dice_min}
                onChange={e => setCreateForm({...createForm, dice_min: parseInt(e.target.value) || 1})} />
            </div>
            <div className="form-group" style={{flex:1}}>
              <div className="form-label">최대값</div>
              <input type="number" value={createForm.dice_max}
                onChange={e => setCreateForm({...createForm, dice_max: parseInt(e.target.value) || 6})} />
            </div>
          </div>
          <div className="form-group">
            <div className="form-label">참가비 (P)</div>
            <input type="number" placeholder="최소 10P" value={createForm.entry_fee}
              onChange={e => setCreateForm({...createForm, entry_fee: e.target.value})} />
          </div>
          <button className="btn btn-primary" onClick={handleCreate}>방 만들기</button>
        </div>
      )}

      {/* 방 목록 */}
      {rooms.length === 0 ? (
        <div className="card" style={{textAlign:'center',color:'var(--text-dim)',padding:40}}>
          열린 게임방이 없습니다. 새 방을 만들어보세요!
        </div>
      ) : (
        rooms.map(r => {
          const isMyRoom = r.creator_id === currentUser?.user_id
          const alreadyIn = r.creator_id === currentUser?.user_id // 방장은 이미 입장
          return (
            <div key={r.id} className="card mb-8 dice-room-card" onClick={() => enterRoom(r.id)}>
              <div className="flex-between">
                <div>
                  <span style={{fontWeight:600}}>{r.mode === 'HIGH' ? `${e('🔺','▲')} HIGH` : `${e('🔻','▼')} LOW`}</span>
                  <span style={{fontSize:12,color:'var(--text-dim)',marginLeft:8}}>by {r.creator_name}</span>
                </div>
                <span className={`badge ${r.status === 'WAITING' ? 'badge-orange' : 'badge-green'}`}>
                  {r.status === 'WAITING' ? `대기중 (${r.player_count}명)` : `진행중 R${r.current_round}`}
                </span>
              </div>
              <div style={{display:'flex',gap:16,marginTop:8,fontSize:12,color:'var(--text-dim)'}}>
                <span>참가비: {fmt(r.entry_fee)}P</span>
                <span>판돈: <strong style={{color:'var(--accent-orange)'}}>{fmt(r.total_pot)}P</strong></span>
                <span>주사위: {r.dice_min}~{r.dice_max}</span>
              </div>
              {r.status === 'WAITING' && !isMyRoom && (
                <button className="btn btn-green mt-8" style={{fontSize:12}}
                  onClick={e => { e.stopPropagation(); handleJoin(r.id) }}
                  disabled={points < r.entry_fee}>
                  {points < r.entry_fee ? '포인트 부족' : '입장하기'}
                </button>
              )}
            </div>
          )
        })
      )}

      {/* 히스토리 모달 */}
      {showHistory && (
        <div className="modal-overlay" onClick={() => setShowHistory(false)}>
          <div className="modal-box" onClick={e => e.stopPropagation()} style={{maxWidth:500}}>
            <div className="flex-between mb-16">
              <div className="card-title" style={{margin:0}}>{e('📜','')} 게임 기록</div>
              <button className="btn btn-outline" onClick={() => setShowHistory(false)} style={{fontSize:12,padding:'4px 8px'}}>닫기</button>
            </div>
            {history.length === 0 ? (
              <div style={{textAlign:'center',color:'var(--text-dim)',padding:20}}>게임 기록이 없습니다</div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>날짜</th><th>모드</th><th>인원</th><th>판돈</th><th>우승자</th></tr></thead>
                  <tbody>
                    {history.map(h => (
                      <tr key={h.id}>
                        <td style={{fontSize:11}}>{h.finished_at?.slice(0,10)}</td>
                        <td>{h.mode}</td>
                        <td className="text-center">{h.player_count}</td>
                        <td className="text-right mono" style={{color:'var(--accent-orange)'}}>{fmt(h.total_pot)}P</td>
                        <td>{h.winner_name}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}


// ═══════════════════════════════════════════════
// ═══════════════════════════════════════════════
// GACHA PAGE (일일 가챠 뽑기)
// ═══════════════════════════════════════════════
const GACHA_GRADE_INFO = () => ({
  MISS:    { label: '꽝',   emoji: e('😭','[꽝]'), color: '#888' },
  SMALL:   { label: '소량', emoji: e('🪙','[소]'), color: '#4caf50' },
  MEDIUM:  { label: '중간', emoji: e('💰','[중]'), color: '#2196f3' },
  JACKPOT: { label: '잭팟', emoji: e('🎉','[잭팟]'), color: '#ff9800' },
})

function GachaPage({ onPointsChange }) {
  const [todayData, setTodayData] = useState(null)
  const [jackpots, setJackpots] = useState([])
  const [spinning, setSpinning] = useState(false)
  const [result, setResult] = useState(null)
  const [animating, setAnimating] = useState(false)

  const load = useCallback(async () => {
    const [td, jp] = await Promise.all([api.getGachaToday(), api.getRecentJackpots()])
    setTodayData(td)
    setJackpots(jp.jackpots)
  }, [])

  useEffect(() => { load() }, [load])

  const handleSpin = async () => {
    if (spinning) return
    setSpinning(true)
    setResult(null)
    setAnimating(true)
    try {
      const res = await api.spinGacha()
      setTimeout(() => {
        setResult(res)
        setAnimating(false)
        onPointsChange && onPointsChange()
        load()
      }, 1200)
    } catch (e) {
      alert(e.message)
      setAnimating(false)
    } finally {
      setSpinning(false)
    }
  }

  const grade = result ? GACHA_GRADE_INFO()[result.grade] : null
  const freeUsed = todayData?.free_used
  const spinCount = todayData?.spin_count ?? 0

  return (
    <div className="page-container">
      <h2>{e('🎰','')} 일일 가챠 뽑기</h2>
      <div className="card gacha-card">
        <div className="gacha-machine">
          <div className={`gacha-display ${animating ? 'gacha-spinning' : ''}`}>
            {animating ? (
              <span className="gacha-spin-icon">{e('🎰','[?]')}</span>
            ) : result ? (
              <div className="gacha-result-inner" style={{ color: grade.color }}>
                <div className="gacha-result-emoji">{grade.emoji}</div>
                <div className="gacha-result-grade">{grade.label}</div>
                {result.points_won > 0 && (
                  <div className="gacha-result-points">+{result.points_won.toLocaleString()}P</div>
                )}
                {result.points_won === 0 && (
                  <div className="gacha-result-points" style={{ color: '#888' }}>획득 포인트 없음</div>
                )}
              </div>
            ) : (
              <span className="gacha-spin-icon">{e('🎰','[?]')}</span>
            )}
          </div>

          <button
            className="btn btn-primary gacha-btn"
            onClick={handleSpin}
            disabled={spinning || animating}
          >
            {animating ? '뽑는 중...' : freeUsed ? `추가 뽑기 (${todayData?.paid_cost}P)` : '무료 뽑기!'}
          </button>

          <div className="gacha-info">
            오늘 {spinCount}회 뽑음 · {freeUsed ? '무료 뽑기 사용됨' : '무료 뽑기 1회 남음'}
          </div>
        </div>

        <div className="gacha-odds">
          <div className="gacha-odds-title">확률표</div>
          <div className="gacha-odds-grid">
            <div style={{ color: GACHA_GRADE_INFO().MISS.color }}>{e('😭','[꽝]')} 꽝 — 50%</div>
            <div style={{ color: GACHA_GRADE_INFO().SMALL.color }}>{e('🪙','[소]')} 소량 (10~50P) — 30%</div>
            <div style={{ color: GACHA_GRADE_INFO().MEDIUM.color }}>{e('💰','[중]')} 중간 (100~300P) — 15%</div>
            <div style={{ color: GACHA_GRADE_INFO().JACKPOT.color }}>{e('🎉','[잭팟]')} 잭팟 (500~2000P) — 5%</div>
          </div>
        </div>
      </div>

      {todayData?.today_spins?.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="card-title">오늘의 뽑기 기록</div>
          <table className="table">
            <thead><tr><th>#</th><th>등급</th><th>획득</th><th>비용</th></tr></thead>
            <tbody>
              {todayData.today_spins.map((s, i) => {
                const gi = GACHA_GRADE_INFO()[s.grade]
                return (
                  <tr key={i}>
                    <td>{i + 1}</td>
                    <td style={{ color: gi.color }}>{gi.emoji} {gi.label}</td>
                    <td>{s.points_won > 0 ? `+${s.points_won}P` : '-'}</td>
                    <td>{s.cost > 0 ? `-${s.cost}P` : '무료'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {jackpots.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="card-title">{e('🎉','')} 최근 잭팟 당첨자</div>
          <table className="table">
            <thead><tr><th>닉네임</th><th>획득</th><th>일시</th></tr></thead>
            <tbody>
              {jackpots.map((j, i) => (
                <tr key={i} className="gacha-jackpot-row">
                  <td>{e('🎉','')} {j.nickname}</td>
                  <td style={{ color: '#ff9800', fontWeight: 700 }}>+{j.points_won.toLocaleString()}P</td>
                  <td style={{ fontSize: 12, color: '#888' }}>{j.created_at?.slice(0, 16)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}


// ═══════════════════════════════════════════════
// OMOK PAGE (오목 - 렌주룰)
// ═══════════════════════════════════════════════
function OmokPage({ onPointsChange }) {
  const [view, setView] = useState('list')
  const [rooms, setRooms] = useState([])
  const [room, setRoom] = useState(null)
  const [points, setPoints] = useState(0)
  const [showCreate, setShowCreate] = useState(false)
  const [betAmount, setBetAmount] = useState('')
  const [history, setHistory] = useState([])
  const [showHistory, setShowHistory] = useState(false)
  const [leaderboard, setLeaderboard] = useState([])
  const [showLeaderboard, setShowLeaderboard] = useState(false)
  const [myMmr, setMyMmr] = useState(null)
  const [loading, setLoading] = useState(true)
  const [lastMove, setLastMove] = useState(null)
  const [specBets, setSpecBets] = useState(null)
  const [specBetAmount, setSpecBetAmount] = useState('')
  const [showWeekly, setShowWeekly] = useState(false)
  const [weeklyData, setWeeklyData] = useState(null)
  const pollingRef = useRef(null)
  const currentUser = api.getUser()

  const loadRooms = async () => {
    try {
      const [rs, p, mmr] = await Promise.all([
        api.getOmokRooms().catch(() => []),
        api.getPoints().catch(() => ({ points: 0 })),
        api.getMyMmr().catch(() => ({})),
      ])
      setRooms(rs); setPoints(p.points); setMyMmr(mmr.omok || null)
    } catch {}
    setLoading(false)
  }

  const loadRoom = async (id) => {
    try {
      const r = await api.getOmokRoom(id)
      setRoom(r)
      if (r.moves && r.moves.length > 0) {
        const last = r.moves[r.moves.length - 1]
        setLastMove({ x: last.x, y: last.y })
      }
      if (r.status === 'FINISHED' || r.status === 'CANCELLED') stopPolling()
    } catch (e) { alert(e.message); goBack() }
  }

  const startPolling = (id) => { stopPolling(); pollingRef.current = setInterval(() => loadRoom(id), 1500) }
  const stopPolling = () => { if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null } }
  const goBack = () => { stopPolling(); setView('list'); setRoom(null); loadRooms(); onPointsChange?.() }

  useEffect(() => { loadRooms(); return () => stopPolling() }, [])

  const enterRoom = async (id) => {
    setLoading(true)
    try { const r = await api.getOmokRoom(id); setRoom(r); setView('room'); startPolling(id); loadSpecBets(id) } catch (e) { alert(e.message) }
    setLoading(false)
  }

  const handleCreate = async () => {
    const bet = parseInt(betAmount) || 0
    if (bet < 0) return alert('베팅 금액이 올바르지 않습니다')
    try {
      const res = await api.createOmokRoom({ bet_amount: bet })
      setShowCreate(false); setBetAmount('')
      enterRoom(res.room_id); onPointsChange?.()
    } catch (e) { alert(e.message) }
  }

  const handleJoin = async (id) => {
    try { await api.joinOmokRoom(id); enterRoom(id); onPointsChange?.() } catch (e) { alert(e.message) }
  }

  const handleMove = async (x, y) => {
    if (!room || room.status !== 'PLAYING') return
    const myColor = room.creator_id === currentUser?.user_id ? room.creator_color : (room.creator_color === 'B' ? 'W' : 'B')
    if (room.current_turn !== myColor) return
    if (room.board[y][x] !== 0) return
    try {
      await api.omokMove(room.id, { x, y })
      setLastMove({ x, y })
      loadRoom(room.id)
      onPointsChange?.()
    } catch (e) { alert(e.message) }
  }

  const handleResign = async () => {
    if (!confirm('기권하시겠습니까?')) return
    try { await api.omokResign(room.id); loadRoom(room.id); onPointsChange?.() } catch (e) { alert(e.message) }
  }

  const handleCancel = async () => {
    try { await api.cancelOmokRoom(room.id); goBack() } catch (e) { alert(e.message) }
  }

  const handleRematch = async () => {
    try { await api.omokRematch(room.id); loadRoom(room.id); onPointsChange?.(); startPolling(room.id) } catch (e) { alert(e.message) }
  }

  const handleUndoRequest = async () => {
    try { await api.omokUndoRequest(room.id); loadRoom(room.id) } catch (e) { alert(e.message) }
  }

  const handleUndoResponse = async (accept) => {
    try { await api.omokUndoResponse(room.id, { accept }); loadRoom(room.id) } catch (e) { alert(e.message) }
  }

  const loadLeaderboard = async () => {
    try { const lb = await api.getMmrLeaderboard('omok'); setLeaderboard(lb); setShowLeaderboard(true) } catch (e) { alert(e.message) }
  }

  const loadHistory = async () => {
    try { const h = await api.getOmokHistory(); setHistory(h); setShowHistory(true) } catch (e) { alert(e.message) }
  }

  const loadSpecBets = async (roomId) => {
    try { const data = await api.getSpectatorBets('omok', roomId); setSpecBets(data) } catch (e) {}
  }

  const handleSpecBet = async (predictedWinnerId) => {
    const amt = parseInt(specBetAmount)
    if (!amt || amt <= 0) return alert('배팅 포인트를 입력하세요')
    try {
      await api.placeSpectatorBet('omok', room.id, { predicted_winner_id: predictedWinnerId, amount: amt })
      setSpecBetAmount('')
      loadSpecBets(room.id)
      onPointsChange?.()
      api.getPoints().then(r => setPoints(r.points)).catch(() => {})
    } catch (e) { alert(e.message) }
  }

  const loadWeekly = async () => {
    try { const data = await api.getWeeklyOmokLeaderboard(); setWeeklyData(data); setShowWeekly(true) } catch (e) { alert(e.message) }
  }

  if (loading) return <div className="loading">로딩 중...</div>

  // ── Room View ──
  if (view === 'room' && room) {
    const isCreator = currentUser?.user_id === room.creator_id
    const isParticipant = currentUser?.user_id === room.creator_id || currentUser?.user_id === room.opponent_id
    const myColor = isCreator ? room.creator_color : (room.creator_color === 'B' ? 'W' : 'B')
    const isMyTurn = isParticipant && room.status === 'PLAYING' && room.current_turn === myColor

    return (
      <div>
        <button className="btn btn-outline mb-16" onClick={goBack} style={{fontSize:12}}>← 목록으로</button>
        <div className="card mb-16">
          <div className="flex-between mb-8">
            <div className="card-title" style={{margin:0}}>
              {e('⚫','')} 오목 #{room.id} (게임 {room.game_number})
            </div>
            <div style={{display:'flex',gap:6,alignItems:'center'}}>
              {!isParticipant && room.status === 'PLAYING' && <span className="badge badge-blue">관전 중</span>}
              <span className={`badge ${room.status === 'PLAYING' ? 'badge-green' : room.status === 'FINISHED' ? 'badge-orange' : 'badge-red'}`}>
                {room.status === 'PLAYING' ? '진행중' : room.status === 'FINISHED' ? '종료' : room.status === 'WAITING' ? '대기중' : '취소됨'}
              </span>
            </div>
          </div>
          <div style={{display:'flex',gap:16,flexWrap:'wrap',fontSize:13,color:'var(--text-dim)'}}>
            <span>흑: <strong style={{color: room.creator_color === 'B' ? 'var(--text)' : 'var(--text-dim)'}}>{room.creator_color === 'B' ? room.creator_name : (room.opponent_name || '대기중')}</strong></span>
            <span>백: <strong style={{color: room.creator_color === 'W' ? 'var(--text)' : 'var(--text-dim)'}}>{room.creator_color === 'W' ? room.creator_name : (room.opponent_name || '대기중')}</strong></span>
            {room.bet_amount > 0 && <span>베팅: <strong style={{color:'var(--accent-orange)'}}>{fmt(room.bet_amount)}P</strong></span>}
            <span>수순: {room.move_count}</span>
            {room.status === 'PLAYING' && (isParticipant
              ? <span style={{color: isMyTurn ? 'var(--green)' : 'var(--red)'}}>{isMyTurn ? '내 차례' : '상대 차례'} ({room.current_turn === 'B' ? '흑' : '백'})</span>
              : <span style={{color:'var(--text-dim)'}}>관전 중 ({room.current_turn === 'B' ? '흑' : '백'} 차례)</span>
            )}
          </div>
        </div>

        {/* 오목판 */}
        <div className="omok-board-wrap">
          {isExcel() && (
            <div className="omok-excel-col-headers">
              <div className="omok-excel-corner" />
              {Array.from({length:19}, (_, x) => (
                <div key={x} className="omok-excel-col-hdr">{String.fromCharCode(65+x)}</div>
              ))}
            </div>
          )}
          <div className={`omok-board${isExcel() ? ' omok-board-excel' : ''}`}>
            {Array.from({length:19}, (_, y) => [
              isExcel() && <div key={`rn-${y}`} className="omok-excel-row-num">{y+1}</div>,
              ...Array.from({length:19}, (_, x) => {
                const stone = room.board?.[y]?.[x]
                const isLast = lastMove && lastMove.x === x && lastMove.y === y
                const isStar = [3,9,15].includes(x) && [3,9,15].includes(y)
                return (
                  <div key={`${x}-${y}`}
                    className={`omok-cell${isMyTurn && stone === 0 ? ' clickable' : ''}${isExcel() && stone === 1 ? ' xls-b' : ''}${isExcel() && stone === 2 ? ' xls-w' : ''}${isExcel() && isLast ? ' xls-last' : ''}`}
                    onClick={() => handleMove(x, y)}>
                    {!isExcel() && isStar && stone === 0 && <div className="omok-star" />}
                    {!isExcel() && stone === 1 && <div className={`omok-stone black${isLast ? ' last-move' : ''}`}>{isLast && <div className="last-dot" />}</div>}
                    {!isExcel() && stone === 2 && <div className={`omok-stone white${isLast ? ' last-move' : ''}`}>{isLast && <div className="last-dot" />}</div>}
                  </div>
                )
              })
            ])}
          </div>
        </div>

        {/* 관전 배팅 (관전자 전용) */}
        {!isParticipant && room.status === 'PLAYING' && (
          <div className="card mb-16">
            <div className="card-title" style={{margin:'0 0 8px'}}>{e('🎯','')} 관전 배팅</div>
            {specBets?.my_bet ? (
              <div style={{fontSize:13,color:'var(--text-dim)'}}>
                이미 배팅 완료: <strong>{specBets.my_bet.predicted_winner_name}</strong>에 <strong>{fmt(specBets.my_bet.amount)}P</strong>
              </div>
            ) : (
              <div>
                <div style={{display:'flex',gap:8,alignItems:'center',marginBottom:8}}>
                  <input type="number" placeholder="포인트" value={specBetAmount} onChange={e => setSpecBetAmount(e.target.value)}
                    style={{width:120}} />
                  <button className="btn btn-primary btn-sm" onClick={() => handleSpecBet(room.creator_id)}>
                    {room.creator_color === 'B' ? '흑' : '백'} {room.creator_name} 예측
                  </button>
                  <button className="btn btn-sell btn-sm" onClick={() => handleSpecBet(room.opponent_id)}>
                    {room.creator_color === 'B' ? '백' : '흑'} {room.opponent_name} 예측
                  </button>
                </div>
                <div style={{fontSize:11,color:'var(--text-dim)'}}>보유: {fmt(points)}P · 적중 시 배당 비례 배분</div>
              </div>
            )}
            {specBets && specBets.bets.length > 0 && (
              <div style={{marginTop:8,fontSize:12}}>
                <div style={{color:'var(--text-dim)',marginBottom:4}}>배팅 현황 (총 {fmt(specBets.total_pool)}P)</div>
                {specBets.bets.filter(b => b.status === 'PENDING').map(b => (
                  <div key={b.id} style={{display:'flex',gap:8,padding:'2px 0'}}>
                    <span>{b.nickname}</span>
                    <span style={{color:'var(--accent-orange)'}}>{fmt(b.amount)}P</span>
                    <span style={{color:'var(--text-dim)'}}>→ {b.predicted_winner_name}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* 관전 배팅 결과 (종료 시) */}
        {!isParticipant && room.status === 'FINISHED' && specBets?.my_bet && (
          <div className="card mb-16" style={{textAlign:'center'}}>
            <div style={{fontSize:14,fontWeight:600,marginBottom:4}}>
              {specBets.my_bet.status === 'WON' ? `${e('🎯','')} 관전 배팅 적중! +${fmt(specBets.my_bet.payout - specBets.my_bet.amount)}P` :
               specBets.my_bet.status === 'LOST' ? '관전 배팅 실패' :
               specBets.my_bet.status === 'REFUNDED' ? `관전 배팅 환불 +${fmt(specBets.my_bet.amount)}P` : ''}
            </div>
          </div>
        )}

        {/* 대기 안내 */}
        {room.status === 'WAITING' && (
          <div className="card mb-16" style={{textAlign:'center',padding:'24px 16px'}}>
            <div style={{fontSize:16,color:'var(--text-dim)',marginBottom:8}}>상대방을 기다리는 중...</div>
            <div style={{fontSize:12,color:'var(--text-dim)'}}>다른 유저가 참가하면 게임이 시작됩니다</div>
          </div>
        )}

        {/* 결과 & 액션 */}
        {room.status === 'FINISHED' && (
          <div className="card mb-16" style={{textAlign:'center'}}>
            {room.winner_id ? (
              <div>
                <div style={{fontSize:18,fontWeight:700,marginBottom:8}}>
                  {room.winner_id === currentUser?.user_id ? `${e('🎉','')} 승리!` : isParticipant ? '패배' : `${room.winner_name || '승자'} 승리`}
                </div>
                <div style={{fontSize:13,color:'var(--text-dim)'}}>
                  사유: {room.win_reason === 'five' ? '5목' : room.win_reason === 'resign' ? '기권' : room.win_reason}
                  {room.bet_amount > 0 && isParticipant && ` | ${room.winner_id === currentUser?.user_id ? '+' : '-'}${fmt(room.bet_amount)}P`}
                </div>
              </div>
            ) : (
              <div style={{fontSize:18,fontWeight:700}}>무승부</div>
            )}
            {isParticipant && (
              <button className="btn btn-primary mt-12" onClick={handleRematch}>{e('🔄','')} 한판더하기</button>
            )}
          </div>
        )}

        {room.status === 'PLAYING' && isParticipant && (() => {
          const myColor = isCreator ? room.creator_color : (room.creator_color === 'B' ? 'W' : 'B')
          const isMyTurnNow = room.current_turn === myColor
          const hasPendingUndo = room.undo_request_by != null
          const iMyUndoReq = room.undo_request_by === currentUser?.user_id
          const isOpponentUndoReq = hasPendingUndo && !iMyUndoReq
          const canRequestUndo = !isMyTurnNow && !hasPendingUndo && room.move_count > 0
          return (
            <div style={{textAlign:'center',marginTop:12,display:'flex',gap:8,justifyContent:'center',flexWrap:'wrap'}}>
              {isOpponentUndoReq && (
                <div className="card" style={{padding:'10px 16px',display:'inline-flex',gap:8,alignItems:'center'}}>
                  <span style={{fontSize:13}}>상대가 한수 무르기를 요청했습니다</span>
                  <button className="btn btn-primary btn-sm" onClick={() => handleUndoResponse(true)}>수락</button>
                  <button className="btn btn-sell btn-sm" onClick={() => handleUndoResponse(false)}>거절</button>
                </div>
              )}
              {iMyUndoReq && (
                <span style={{fontSize:13,color:'var(--text-dim)',alignSelf:'center'}}>한수 무르기 요청 중...</span>
              )}
              {canRequestUndo && (
                <button className="btn btn-ghost" onClick={handleUndoRequest}>한수 무르기</button>
              )}
              <button className="btn btn-sell" onClick={handleResign}>기권</button>
            </div>
          )
        })()}
        {room.status === 'WAITING' && isCreator && (
          <div style={{textAlign:'center',marginTop:12}}>
            <button className="btn btn-sell" onClick={handleCancel}>방 취소</button>
          </div>
        )}
      </div>
    )
  }

  // ── List View ──
  return (
    <div>
      <div className="flex-between mb-16">
        <h2 style={{margin:0}}>{e('⚫','')} 오목 (렌주룰)</h2>
        <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
          {myMmr && <span className="badge badge-blue" style={{alignSelf:'center'}}>MMR {myMmr.mmr}</span>}
          <button className="btn btn-ghost" onClick={loadLeaderboard}>{e('🏆','')} 리더보드</button>
          <button className="btn btn-ghost" onClick={loadWeekly}>{e('📅','')} 주간</button>
          <button className="btn btn-ghost" onClick={loadHistory}>{e('📜','')} 전적</button>
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>+ 방 만들기</button>
        </div>
      </div>

      <div className="card mb-8" style={{fontSize:12,color:'var(--text-dim)',padding:'8px 16px'}}>
        렌주룰: 방장이 흑(선공). 흑은 쌍삼/쌍사/장목 금지. 한판더하기 시 흑백 스왑.
      </div>

      {showCreate && (
        <div className="card mb-16">
          <div className="card-title">방 만들기</div>
          <div style={{display:'flex',gap:8,alignItems:'center'}}>
            <input type="number" placeholder="베팅 포인트 (0=무료)" value={betAmount} onChange={e => setBetAmount(e.target.value)} style={{width:160}} />
            <button className="btn btn-primary" onClick={handleCreate}>생성</button>
            <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>취소</button>
          </div>
          <div style={{fontSize:12,color:'var(--text-dim)',marginTop:4}}>보유: {fmt(points)}P</div>
        </div>
      )}

      {rooms.length === 0 ? (
        <div className="card" style={{textAlign:'center',color:'var(--text-dim)'}}>대기 중인 방이 없습니다</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>#</th><th>방장</th><th>상대</th><th>베팅</th><th>상태</th><th></th></tr></thead>
            <tbody>
              {rooms.map(r => (
                <tr key={r.id}>
                  <td>{r.id}</td>
                  <td>{r.creator_name}</td>
                  <td>{r.opponent_name || '-'}</td>
                  <td>{r.bet_amount > 0 ? `${fmt(r.bet_amount)}P` : '무료'}</td>
                  <td><span className={`badge ${r.status === 'PLAYING' ? 'badge-green' : 'badge-orange'}`}>{r.status === 'PLAYING' ? '진행중' : '대기중'}</span></td>
                  <td>
                    {r.status === 'WAITING' && r.creator_id !== currentUser?.user_id && (
                      <button className="btn btn-primary btn-sm" onClick={() => handleJoin(r.id)}>참가</button>
                    )}
                    {(r.creator_id === currentUser?.user_id || r.opponent_id === currentUser?.user_id) && (
                      <button className="btn btn-ghost btn-sm" onClick={() => enterRoom(r.id)}>입장</button>
                    )}
                    {r.status === 'PLAYING' && r.creator_id !== currentUser?.user_id && r.opponent_id !== currentUser?.user_id && (
                      <button className="btn btn-ghost btn-sm" onClick={() => enterRoom(r.id)}>관전</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 리더보드 모달 */}
      {showLeaderboard && (
        <div className="modal-overlay" onClick={() => setShowLeaderboard(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="flex-between mb-16">
              <h3 style={{margin:0}}>{e('🏆','')} 오목 MMR 리더보드</h3>
              <button className="btn btn-ghost" onClick={() => setShowLeaderboard(false)}>✕</button>
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>#</th><th>닉네임</th><th>MMR</th><th>승</th><th>패</th><th>무</th><th>승률</th></tr></thead>
                <tbody>
                  {leaderboard.map((r, i) => (
                    <tr key={r.user_id} className={r.user_id === currentUser?.user_id ? 'highlight-row' : ''}>
                      <td className={rankClass(i+1)}>{i+1}</td>
                      <td>{r.nickname}</td>
                      <td><strong>{r.mmr}</strong></td>
                      <td style={{color:'var(--green)'}}>{r.wins}</td>
                      <td style={{color:'var(--red)'}}>{r.losses}</td>
                      <td>{r.draws}</td>
                      <td>{r.wins + r.losses > 0 ? ((r.wins / (r.wins + r.losses)) * 100).toFixed(1) + '%' : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* 전적 모달 */}
      {showHistory && (
        <div className="modal-overlay" onClick={() => setShowHistory(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="flex-between mb-16">
              <h3 style={{margin:0}}>{e('📜','')} 오목 전적</h3>
              <button className="btn btn-ghost" onClick={() => setShowHistory(false)}>✕</button>
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>상대</th><th>결과</th><th>수순</th><th>베팅</th><th>시간</th></tr></thead>
                <tbody>
                  {history.map(r => {
                    const isWin = r.winner_id === currentUser?.user_id
                    const isDraw = !r.winner_id
                    const opponent = r.creator_id === currentUser?.user_id ? r.opponent_name : r.creator_name
                    return (
                      <tr key={r.id}>
                        <td>{opponent}</td>
                        <td style={{color: isDraw ? 'var(--text-dim)' : isWin ? 'var(--green)' : 'var(--red)', fontWeight:700}}>
                          {isDraw ? '무승부' : isWin ? '승' : '패'}
                        </td>
                        <td>{r.move_count}수</td>
                        <td>{r.bet_amount > 0 ? `${fmt(r.bet_amount)}P` : '-'}</td>
                        <td style={{fontSize:11,color:'var(--text-dim)'}}>{r.finished_at?.slice(5,16)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* 주간 리더보드 모달 */}
      {showWeekly && weeklyData && (
        <div className="modal-overlay" onClick={() => setShowWeekly(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="flex-between mb-16">
              <h3 style={{margin:0}}>{e('📅','')} 오목 주간 리더보드</h3>
              <button className="btn btn-ghost" onClick={() => setShowWeekly(false)}>✕</button>
            </div>
            <div style={{fontSize:12,color:'var(--text-dim)',marginBottom:12}}>
              {weeklyData.week_start} ~ {weeklyData.week_end}
              {weeklyData.rewarded && <span className="badge badge-green" style={{marginLeft:8}}>보상 지급 완료</span>}
            </div>
            <div style={{fontSize:12,color:'var(--accent-orange)',marginBottom:12}}>
              주간 보상: 1등 3,000P / 2등 2,000P / 3등 1,000P
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>#</th><th>닉네임</th><th>MMR</th><th>승</th><th>패</th><th>승률</th></tr></thead>
                <tbody>
                  {weeklyData.leaderboard.map((r, i) => (
                    <tr key={r.user_id} className={r.user_id === currentUser?.user_id ? 'highlight-row' : ''}>
                      <td className={rankClass(i+1)}>{i+1} {i < 3 ? ['🥇','🥈','🥉'][i] : ''}</td>
                      <td>{r.nickname}</td>
                      <td><strong>{r.mmr}</strong></td>
                      <td style={{color:'var(--green)'}}>{r.wins}</td>
                      <td style={{color:'var(--red)'}}>{r.losses}</td>
                      <td>{r.wins + r.losses > 0 ? ((r.wins / (r.wins + r.losses)) * 100).toFixed(1) + '%' : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}


// ═══════════════════════════════════════════════
// CHESS PAGE (체스)
// ═══════════════════════════════════════════════

// ── Minimal Chess Engine (client-side) ──
const CHESS_INITIAL_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

function parseFEN(fen) {
  const [board, turn, castling, ep, halfmove, fullmove] = fen.split(' ')
  const squares = []
  for (const row of board.split('/')) {
    const r = []
    for (const c of row) {
      if (c >= '1' && c <= '8') for (let i = 0; i < parseInt(c); i++) r.push(null)
      else r.push(c)
    }
    squares.push(r)
  }
  return { squares, turn, castling, ep: ep === '-' ? null : ep, halfmove: parseInt(halfmove), fullmove: parseInt(fullmove) }
}

function toFEN(state) {
  let fen = ''
  for (let r = 0; r < 8; r++) {
    let empty = 0
    for (let c = 0; c < 8; c++) {
      if (!state.squares[r][c]) { empty++ }
      else { if (empty) { fen += empty; empty = 0 } fen += state.squares[r][c] }
    }
    if (empty) fen += empty
    if (r < 7) fen += '/'
  }
  return `${fen} ${state.turn} ${state.castling || '-'} ${state.ep || '-'} ${state.halfmove} ${state.fullmove}`
}

function sqToRC(sq) { return [8 - parseInt(sq[1]), sq.charCodeAt(0) - 97] }
function rcToSq(r, c) { return String.fromCharCode(97 + c) + (8 - r) }

function isWhite(p) { return p && p === p.toUpperCase() }
function isBlack(p) { return p && p === p.toLowerCase() }
function colorOf(p) { return p ? (isWhite(p) ? 'w' : 'b') : null }

function getValidMoves(state) {
  // Returns map: "e2" -> ["e3","e4"] etc.
  const moves = {}
  const { squares, turn, castling, ep } = state
  const isW = turn === 'w'

  for (let r = 0; r < 8; r++) {
    for (let c = 0; c < 8; c++) {
      const p = squares[r][c]
      if (!p || (isW ? isBlack(p) : isWhite(p))) continue
      const from = rcToSq(r, c)
      const targets = []
      const pt = p.toLowerCase()

      const addIfValid = (tr, tc) => {
        if (tr < 0 || tr > 7 || tc < 0 || tc > 7) return false
        const tp = squares[tr][tc]
        if (tp && colorOf(tp) === turn) return false
        targets.push(rcToSq(tr, tc))
        return !tp // can continue sliding?
      }

      if (pt === 'p') {
        const dir = isW ? -1 : 1
        const startRow = isW ? 6 : 1
        // Forward
        if (r+dir >= 0 && r+dir <= 7 && !squares[r+dir][c]) {
          targets.push(rcToSq(r+dir, c))
          if (r === startRow && !squares[r+2*dir][c]) targets.push(rcToSq(r+2*dir, c))
        }
        // Captures
        for (const dc of [-1, 1]) {
          const tr = r+dir, tc = c+dc
          if (tc < 0 || tc > 7 || tr < 0 || tr > 7) continue
          const tp = squares[tr][tc]
          if (tp && colorOf(tp) !== turn) targets.push(rcToSq(tr, tc))
          // En passant
          if (ep && rcToSq(tr, tc) === ep) targets.push(ep)
        }
      } else if (pt === 'n') {
        for (const [dr,dc] of [[-2,-1],[-2,1],[-1,-2],[-1,2],[1,-2],[1,2],[2,-1],[2,1]]) addIfValid(r+dr, c+dc)
      } else if (pt === 'b') {
        for (const [dr,dc] of [[-1,-1],[-1,1],[1,-1],[1,1]]) { for (let i=1;i<8;i++) { if(!addIfValid(r+dr*i,c+dc*i)) break } }
      } else if (pt === 'r') {
        for (const [dr,dc] of [[-1,0],[1,0],[0,-1],[0,1]]) { for (let i=1;i<8;i++) { if(!addIfValid(r+dr*i,c+dc*i)) break } }
      } else if (pt === 'q') {
        for (const [dr,dc] of [[-1,-1],[-1,0],[-1,1],[0,-1],[0,1],[1,-1],[1,0],[1,1]]) { for (let i=1;i<8;i++) { if(!addIfValid(r+dr*i,c+dc*i)) break } }
      } else if (pt === 'k') {
        for (const [dr,dc] of [[-1,-1],[-1,0],[-1,1],[0,-1],[0,1],[1,-1],[1,0],[1,1]]) addIfValid(r+dr, c+dc)
        // Castling
        const kRow = isW ? 7 : 0
        if (r === kRow && c === 4) {
          const ks = isW ? 'K' : 'k'
          const qs = isW ? 'Q' : 'q'
          if (castling.includes(ks) && !squares[kRow][5] && !squares[kRow][6] && squares[kRow][7]?.toLowerCase() === 'r') {
            if (!isSquareAttacked(squares, kRow, 4, turn) && !isSquareAttacked(squares, kRow, 5, turn) && !isSquareAttacked(squares, kRow, 6, turn))
              targets.push(rcToSq(kRow, 6))
          }
          if (castling.includes(qs) && !squares[kRow][3] && !squares[kRow][2] && !squares[kRow][1] && squares[kRow][0]?.toLowerCase() === 'r') {
            if (!isSquareAttacked(squares, kRow, 4, turn) && !isSquareAttacked(squares, kRow, 3, turn) && !isSquareAttacked(squares, kRow, 2, turn))
              targets.push(rcToSq(kRow, 2))
          }
        }
      }

      // Filter moves that leave king in check
      const legal = targets.filter(to => {
        const ns = applyMoveRaw(state, from, to)
        return !isInCheck(ns.squares, turn)
      })
      if (legal.length > 0) moves[from] = legal
    }
  }
  return moves
}

function isSquareAttacked(squares, r, c, byColor) {
  // Is square (r,c) attacked by opponent of byColor?
  const opp = byColor === 'w' ? 'b' : 'w'
  // Knight attacks
  for (const [dr,dc] of [[-2,-1],[-2,1],[-1,-2],[-1,2],[1,-2],[1,2],[2,-1],[2,1]]) {
    const tr=r+dr,tc=c+dc
    if (tr>=0&&tr<=7&&tc>=0&&tc<=7) {
      const p = squares[tr][tc]
      if (p && colorOf(p)===opp && p.toLowerCase()==='n') return true
    }
  }
  // King attacks
  for (const [dr,dc] of [[-1,-1],[-1,0],[-1,1],[0,-1],[0,1],[1,-1],[1,0],[1,1]]) {
    const tr=r+dr,tc=c+dc
    if (tr>=0&&tr<=7&&tc>=0&&tc<=7) {
      const p = squares[tr][tc]
      if (p && colorOf(p)===opp && p.toLowerCase()==='k') return true
    }
  }
  // Pawn attacks
  const pDir = byColor === 'w' ? -1 : 1
  for (const dc of [-1,1]) {
    const tr=r+pDir,tc=c+dc
    if (tr>=0&&tr<=7&&tc>=0&&tc<=7) {
      const p = squares[tr][tc]
      if (p && colorOf(p)===opp && p.toLowerCase()==='p') return true
    }
  }
  // Sliding: bishop/queen diagonals
  for (const [dr,dc] of [[-1,-1],[-1,1],[1,-1],[1,1]]) {
    for (let i=1;i<8;i++) {
      const tr=r+dr*i,tc=c+dc*i
      if (tr<0||tr>7||tc<0||tc>7) break
      const p = squares[tr][tc]
      if (p) { if (colorOf(p)===opp && (p.toLowerCase()==='b'||p.toLowerCase()==='q')) return true; break }
    }
  }
  // Sliding: rook/queen lines
  for (const [dr,dc] of [[-1,0],[1,0],[0,-1],[0,1]]) {
    for (let i=1;i<8;i++) {
      const tr=r+dr*i,tc=c+dc*i
      if (tr<0||tr>7||tc<0||tc>7) break
      const p = squares[tr][tc]
      if (p) { if (colorOf(p)===opp && (p.toLowerCase()==='r'||p.toLowerCase()==='q')) return true; break }
    }
  }
  return false
}

function isInCheck(squares, color) {
  // Find king
  const k = color === 'w' ? 'K' : 'k'
  for (let r=0;r<8;r++) for (let c=0;c<8;c++) if (squares[r][c]===k) return isSquareAttacked(squares, r, c, color)
  return false
}

function applyMoveRaw(state, from, to, promotion) {
  const [fr,fc] = sqToRC(from)
  const [tr,tc] = sqToRC(to)
  const newSq = state.squares.map(row => [...row])
  const piece = newSq[fr][fc]
  const captured = newSq[tr][tc]
  const pt = piece?.toLowerCase()
  const isW = state.turn === 'w'

  newSq[tr][tc] = piece
  newSq[fr][fc] = null

  let newEp = null
  let newCastling = state.castling

  // Pawn specials
  if (pt === 'p') {
    // En passant capture
    if (state.ep && to === state.ep) {
      const epRow = isW ? tr+1 : tr-1
      newSq[epRow][tc] = null
    }
    // Double push -> set ep
    if (Math.abs(fr-tr) === 2) {
      newEp = rcToSq((fr+tr)/2, fc)
    }
    // Promotion
    if (tr === 0 || tr === 7) {
      const promo = promotion || 'q'
      newSq[tr][tc] = isW ? promo.toUpperCase() : promo.toLowerCase()
    }
  }

  // Castling move
  if (pt === 'k') {
    if (Math.abs(fc-tc) === 2) {
      if (tc === 6) { newSq[fr][5] = newSq[fr][7]; newSq[fr][7] = null } // kingside
      if (tc === 2) { newSq[fr][3] = newSq[fr][0]; newSq[fr][0] = null } // queenside
    }
    newCastling = newCastling.replace(isW ? /[KQ]/g : /[kq]/g, '')
  }
  if (pt === 'r') {
    if (isW) {
      if (fr===7&&fc===7) newCastling = newCastling.replace('K','')
      if (fr===7&&fc===0) newCastling = newCastling.replace('Q','')
    } else {
      if (fr===0&&fc===7) newCastling = newCastling.replace('k','')
      if (fr===0&&fc===0) newCastling = newCastling.replace('q','')
    }
  }
  // Rook captured
  if (tr===0&&tc===7) newCastling = newCastling.replace('k','')
  if (tr===0&&tc===0) newCastling = newCastling.replace('q','')
  if (tr===7&&tc===7) newCastling = newCastling.replace('K','')
  if (tr===7&&tc===0) newCastling = newCastling.replace('Q','')

  if (!newCastling) newCastling = '-'

  const newTurn = state.turn === 'w' ? 'b' : 'w'
  const newHalfmove = (pt === 'p' || captured) ? 0 : state.halfmove + 1
  const newFullmove = state.fullmove + (state.turn === 'b' ? 1 : 0)

  return { squares: newSq, turn: newTurn, castling: newCastling, ep: newEp, halfmove: newHalfmove, fullmove: newFullmove }
}

const PIECE_UNICODE = { K:'♔', Q:'♕', R:'♖', B:'♗', N:'♘', P:'♙', k:'♚', q:'♛', r:'♜', b:'♝', n:'♞', p:'♟' }

function ChessPage({ onPointsChange }) {
  const [view, setView] = useState('list')
  const [rooms, setRooms] = useState([])
  const [room, setRoom] = useState(null)
  const [points, setPoints] = useState(0)
  const [showCreate, setShowCreate] = useState(false)
  const [betAmount, setBetAmount] = useState('')
  const [history, setHistory] = useState([])
  const [showHistory, setShowHistory] = useState(false)
  const [leaderboard, setLeaderboard] = useState([])
  const [showLeaderboard, setShowLeaderboard] = useState(false)
  const [myMmr, setMyMmr] = useState(null)
  const [loading, setLoading] = useState(true)
  const [gameState, setGameState] = useState(null)
  const [validMoves, setValidMoves] = useState({})
  const [selectedSq, setSelectedSq] = useState(null)
  const [promotionPending, setPromotionPending] = useState(null)
  const [specBets, setSpecBets] = useState(null)
  const [specBetAmount, setSpecBetAmount] = useState('')
  const pollingRef = useRef(null)
  const lastFenRef = useRef(null)
  const currentUser = api.getUser()

  const loadRooms = async () => {
    try {
      const [rs, p, mmr] = await Promise.all([
        api.getChessRooms().catch(() => []),
        api.getPoints().catch(() => ({ points: 0 })),
        api.getMyMmr().catch(() => ({})),
      ])
      setRooms(rs); setPoints(p.points); setMyMmr(mmr.chess || null)
    } catch {}
    setLoading(false)
  }

  const loadRoom = async (id) => {
    try {
      const r = await api.getChessRoom(id)
      setRoom(r)
      // WAITING 상태에서도 초기 보드 렌더링
      {
        const gs = parseFEN(r.fen || CHESS_INITIAL_FEN)
        setGameState(gs)
        lastFenRef.current = r.fen
        if (r.status === 'PLAYING') setValidMoves(getValidMoves(gs))
        else setValidMoves({})
      }
      if (r.status === 'FINISHED' || r.status === 'CANCELLED') stopPolling()
    } catch (e) { alert(e.message); goBack() }
  }

  const startPolling = (id) => { stopPolling(); pollingRef.current = setInterval(() => loadRoom(id), 1500) }
  const stopPolling = () => { if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null } }
  const goBack = () => { stopPolling(); setView('list'); setRoom(null); setGameState(null); setSelectedSq(null); loadRooms(); onPointsChange?.() }

  useEffect(() => { loadRooms(); return () => stopPolling() }, [])

  const enterRoom = async (id) => {
    setLoading(true)
    try { await loadRoom(id); setView('room'); startPolling(id); loadSpecBets(id) } catch (e) { alert(e.message) }
    setLoading(false)
  }

  const handleCreate = async () => {
    const bet = parseInt(betAmount) || 0
    if (bet < 0) return alert('베팅 금액이 올바르지 않습니다')
    try {
      const res = await api.createChessRoom({ bet_amount: bet })
      setShowCreate(false); setBetAmount('')
      enterRoom(res.room_id); onPointsChange?.()
    } catch (e) { alert(e.message) }
  }

  const handleJoin = async (id) => {
    try { await api.joinChessRoom(id); enterRoom(id); onPointsChange?.() } catch (e) { alert(e.message) }
  }

  const getMyColor = () => {
    if (!room) return null
    if (currentUser?.user_id === room.creator_id) return room.creator_color
    if (currentUser?.user_id === room.opponent_id) return room.creator_color === 'w' ? 'b' : 'w'
    return null
  }

  const handleSquareClick = (r, c) => {
    if (!room || room.status !== 'PLAYING' || !gameState) return
    const myColor = getMyColor()
    if (gameState.turn !== myColor) return

    const sq = rcToSq(r, c)
    const piece = gameState.squares[r][c]

    if (selectedSq) {
      const targets = validMoves[selectedSq] || []
      if (targets.includes(sq)) {
        // Check pawn promotion
        const [fr] = sqToRC(selectedSq)
        const movingPiece = gameState.squares[fr][selectedSq.charCodeAt(0)-97]
        if (movingPiece?.toLowerCase() === 'p' && (r === 0 || r === 7)) {
          setPromotionPending({ from: selectedSq, to: sq })
          return
        }
        executeMove(selectedSq, sq)
        return
      }
      // Select new piece
      if (piece && colorOf(piece) === myColor) { setSelectedSq(sq); return }
      setSelectedSq(null)
      return
    }

    if (piece && colorOf(piece) === myColor && validMoves[sq]) {
      setSelectedSq(sq)
    }
  }

  const executeMove = async (from, to, promotion) => {
    const newState = applyMoveRaw(gameState, from, to, promotion)
    const newFen = toFEN(newState)
    const oppMoves = getValidMoves(newState)
    const noMoves = Object.keys(oppMoves).length === 0
    const inCheck = isInCheck(newState.squares, newState.turn)
    const isCheckmate = noMoves && inCheck
    const isStalemate = noMoves && !inCheck
    // 50-move rule or insufficient material simplified
    const isDraw = isStalemate || newState.halfmove >= 100

    try {
      await api.chessMove(room.id, {
        move_from: from, move_to: to, promotion: promotion || null,
        fen_after: newFen, is_checkmate: isCheckmate, is_stalemate: isStalemate, is_draw: isDraw
      })
      setSelectedSq(null)
      setPromotionPending(null)
      loadRoom(room.id)
      onPointsChange?.()
    } catch (e) { alert(e.message) }
  }

  const handleResign = async () => {
    if (!confirm('기권하시겠습니까?')) return
    try { await api.chessResign(room.id); loadRoom(room.id); onPointsChange?.() } catch (e) { alert(e.message) }
  }

  const handleCancel = async () => {
    try { await api.cancelChessRoom(room.id); goBack() } catch (e) { alert(e.message) }
  }

  const handleRematch = async () => {
    try { await api.chessRematch(room.id); loadRoom(room.id); onPointsChange?.(); startPolling(room.id) } catch (e) { alert(e.message) }
  }

  const handleUndoRequest = async () => {
    try { await api.chessUndoRequest(room.id); loadRoom(room.id) } catch (e) { alert(e.message) }
  }

  const handleUndoResponse = async (accept) => {
    try {
      await api.chessUndoResponse(room.id, { accept })
      loadRoom(room.id)
    } catch (e) { alert(e.message) }
  }

  const loadLeaderboard = async () => {
    try { const lb = await api.getMmrLeaderboard('chess'); setLeaderboard(lb); setShowLeaderboard(true) } catch (e) { alert(e.message) }
  }
  const loadHistory = async () => {
    try { const h = await api.getChessHistory(); setHistory(h); setShowHistory(true) } catch (e) { alert(e.message) }
  }

  const loadSpecBets = async (roomId) => {
    try { const data = await api.getSpectatorBets('chess', roomId); setSpecBets(data) } catch (e) {}
  }

  const handleSpecBet = async (predictedWinnerId) => {
    const amt = parseInt(specBetAmount)
    if (!amt || amt <= 0) return alert('배팅 포인트를 입력하세요')
    try {
      await api.placeSpectatorBet('chess', room.id, { predicted_winner_id: predictedWinnerId, amount: amt })
      setSpecBetAmount('')
      loadSpecBets(room.id)
      onPointsChange?.()
      api.getPoints().then(r => setPoints(r.points)).catch(() => {})
    } catch (e) { alert(e.message) }
  }

  if (loading) return <div className="loading">로딩 중...</div>

  // ── Room View ──
  if (view === 'room' && room) {
    const isCreator = currentUser?.user_id === room.creator_id
    const isParticipant = currentUser?.user_id === room.creator_id || currentUser?.user_id === room.opponent_id
    const myColor = getMyColor()
    const isMyTurn = room.status === 'PLAYING' && gameState?.turn === myColor
    const flipped = myColor === 'b'

    const whitePlayer = room.creator_color === 'w' ? room.creator_name : (room.opponent_name || '대기중')
    const blackPlayer = room.creator_color === 'b' ? room.creator_name : (room.opponent_name || '대기중')

    const renderBoard = () => {
      const rows = []
      for (let ri = 0; ri < 8; ri++) {
        const r = flipped ? 7 - ri : ri
        for (let ci = 0; ci < 8; ci++) {
          const c = flipped ? 7 - ci : ci
          const sq = rcToSq(r, c)
          const piece = gameState?.squares[r][c]
          const isLight = (r + c) % 2 === 0
          const isSelected = sq === selectedSq
          const isTarget = selectedSq && (validMoves[selectedSq] || []).includes(sq)
          const isLastMove = room.last_move && (sq === room.last_move.split('-')[0] || sq === room.last_move.split('-')[1])
          rows.push(
            <div key={sq}
              className={`chess-cell ${isLight ? 'light' : 'dark'} ${isSelected ? 'selected' : ''} ${isTarget ? 'target' : ''} ${isLastMove ? 'last-move' : ''}`}
              onClick={() => handleSquareClick(r, c)}>
              {piece && <span className={`chess-piece ${isWhite(piece) ? 'white-piece' : 'black-piece'}`}>{PIECE_UNICODE[piece]}</span>}
              {isTarget && !piece && <div className="move-dot" />}
              {isTarget && piece && <div className="capture-ring" />}
              {ci === 0 && <span className="chess-coord-row">{8-r}</span>}
              {ri === 7 && <span className="chess-coord-col">{String.fromCharCode(flipped ? 104-ci : 97+ci)}</span>}
            </div>
          )
        }
      }
      return rows
    }

    return (
      <div>
        <button className="btn btn-outline mb-16" onClick={goBack} style={{fontSize:12}}>← 목록으로</button>
        <div className="card mb-16">
          <div className="flex-between mb-8">
            <div className="card-title" style={{margin:0}}>♟️ 체스 #{room.id} (게임 {room.game_number})</div>
            <div style={{display:'flex',gap:6,alignItems:'center'}}>
              {!isParticipant && room.status === 'PLAYING' && <span className="badge badge-blue">관전 중</span>}
              <span className={`badge ${room.status === 'PLAYING' ? 'badge-green' : room.status === 'FINISHED' ? 'badge-orange' : 'badge-red'}`}>
                {room.status === 'PLAYING' ? '진행중' : room.status === 'FINISHED' ? '종료' : room.status === 'WAITING' ? '대기중' : '취소됨'}
              </span>
            </div>
          </div>
          <div style={{display:'flex',gap:16,flexWrap:'wrap',fontSize:13,color:'var(--text-dim)'}}>
            <span>백: <strong>{whitePlayer}</strong></span>
            <span>흑: <strong>{blackPlayer}</strong></span>
            {room.bet_amount > 0 && <span>베팅: <strong style={{color:'var(--accent-orange)'}}>{fmt(room.bet_amount)}P</strong></span>}
            <span>수순: {room.move_count}</span>
            {room.status === 'PLAYING' && (isParticipant
              ? <span style={{color: isMyTurn ? 'var(--green)' : 'var(--red)'}}>{isMyTurn ? '내 차례' : '상대 차례'} ({gameState?.turn === 'w' ? '백' : '흑'})</span>
              : <span style={{color:'var(--text-dim)'}}>관전 중 ({gameState?.turn === 'w' ? '백' : '흑'} 차례)</span>
            )}
          </div>
        </div>

        {/* 상대 이름 */}
        <div style={{textAlign:'center',fontSize:13,marginBottom:4,color:'var(--text-dim)'}}>
          {flipped ? whitePlayer : blackPlayer} {flipped ? '(백)' : '(흑)'}
        </div>

        {/* 체스보드 */}
        <div className="chess-board-wrap">
          <div className="chess-board">{gameState && renderBoard()}</div>
        </div>

        {/* 내 이름 */}
        <div style={{textAlign:'center',fontSize:13,marginTop:4,color:'var(--text-dim)'}}>
          {flipped ? blackPlayer : whitePlayer} {flipped ? '(흑)' : '(백)'}
        </div>

        {/* 프로모션 선택 */}
        {promotionPending && (
          <div className="card mb-16" style={{textAlign:'center'}}>
            <div style={{fontSize:14,marginBottom:8}}>프로모션 선택</div>
            <div style={{display:'flex',justifyContent:'center',gap:12}}>
              {['q','r','b','n'].map(p => (
                <button key={p} className="btn btn-primary chess-promo-btn"
                  onClick={() => executeMove(promotionPending.from, promotionPending.to, p)}>
                  {PIECE_UNICODE[myColor === 'w' ? p.toUpperCase() : p]}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* 관전 배팅 (관전자 전용) */}
        {!isParticipant && room.status === 'PLAYING' && (
          <div className="card mb-16">
            <div className="card-title" style={{margin:'0 0 8px'}}>{e('🎯','')} 관전 배팅</div>
            {specBets?.my_bet ? (
              <div style={{fontSize:13,color:'var(--text-dim)'}}>
                이미 배팅 완료: <strong>{specBets.my_bet.predicted_winner_name}</strong>에 <strong>{fmt(specBets.my_bet.amount)}P</strong>
              </div>
            ) : (
              <div>
                <div style={{display:'flex',gap:8,alignItems:'center',marginBottom:8}}>
                  <input type="number" placeholder="포인트" value={specBetAmount} onChange={e => setSpecBetAmount(e.target.value)}
                    style={{width:120}} />
                  <button className="btn btn-primary btn-sm" onClick={() => handleSpecBet(room.creator_id)}>
                    {whitePlayer === room.creator_name ? '백' : '흑'} {room.creator_name} 예측
                  </button>
                  <button className="btn btn-sell btn-sm" onClick={() => handleSpecBet(room.opponent_id)}>
                    {whitePlayer === room.creator_name ? '흑' : '백'} {room.opponent_name} 예측
                  </button>
                </div>
                <div style={{fontSize:11,color:'var(--text-dim)'}}>보유: {fmt(points)}P · 적중 시 배당 비례 배분</div>
              </div>
            )}
            {specBets && specBets.bets.length > 0 && (
              <div style={{marginTop:8,fontSize:12}}>
                <div style={{color:'var(--text-dim)',marginBottom:4}}>배팅 현황 (총 {fmt(specBets.total_pool)}P)</div>
                {specBets.bets.filter(b => b.status === 'PENDING').map(b => (
                  <div key={b.id} style={{display:'flex',gap:8,padding:'2px 0'}}>
                    <span>{b.nickname}</span>
                    <span style={{color:'var(--accent-orange)'}}>{fmt(b.amount)}P</span>
                    <span style={{color:'var(--text-dim)'}}>→ {b.predicted_winner_name}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* 관전 배팅 결과 (종료 시) */}
        {!isParticipant && room.status === 'FINISHED' && specBets?.my_bet && (
          <div className="card mb-16" style={{textAlign:'center'}}>
            <div style={{fontSize:14,fontWeight:600,marginBottom:4}}>
              {specBets.my_bet.status === 'WON' ? `${e('🎯','')} 관전 배팅 적중! +${fmt(specBets.my_bet.payout - specBets.my_bet.amount)}P` :
               specBets.my_bet.status === 'LOST' ? '관전 배팅 실패' :
               specBets.my_bet.status === 'REFUNDED' ? `관전 배팅 환불 +${fmt(specBets.my_bet.amount)}P` : ''}
            </div>
          </div>
        )}

        {/* 대기 안내 */}
        {room.status === 'WAITING' && (
          <div className="card mb-16" style={{textAlign:'center',padding:'24px 16px'}}>
            <div style={{fontSize:16,color:'var(--text-dim)',marginBottom:8}}>상대방을 기다리는 중...</div>
            <div style={{fontSize:12,color:'var(--text-dim)'}}>다른 유저가 참가하면 게임이 시작됩니다</div>
          </div>
        )}

        {/* 결과 */}
        {room.status === 'FINISHED' && (
          <div className="card mb-16" style={{textAlign:'center'}}>
            {room.winner_id ? (
              <div>
                <div style={{fontSize:18,fontWeight:700,marginBottom:8}}>
                  {room.winner_id === currentUser?.user_id ? `${e('🎉','')} 승리!` : isParticipant ? '패배' : `${room.winner_name || '승자'} 승리`}
                </div>
                <div style={{fontSize:13,color:'var(--text-dim)'}}>
                  사유: {room.win_reason === 'checkmate' ? '체크메이트' : room.win_reason === 'resign' ? '기권' : room.win_reason}
                  {room.bet_amount > 0 && isParticipant && ` | ${room.winner_id === currentUser?.user_id ? '+' : '-'}${fmt(room.bet_amount)}P`}
                </div>
              </div>
            ) : (
              <div style={{fontSize:18,fontWeight:700}}>무승부 ({room.win_reason === 'draw' ? '스테일메이트/50수' : room.win_reason})</div>
            )}
            {isParticipant && (
              <button className="btn btn-primary mt-12" onClick={handleRematch}>{e('🔄','')} 한판더하기</button>
            )}
          </div>
        )}

        {room.status === 'PLAYING' && isParticipant && (() => {
          const isMyTurnNow = gameState?.turn === myColor
          const hasPendingUndo = room.undo_request_by != null
          const iMyUndoReq = room.undo_request_by === currentUser?.user_id
          const isOpponentUndoReq = hasPendingUndo && !iMyUndoReq
          const canRequestUndo = !isMyTurnNow && !hasPendingUndo && room.move_count > 0
          return (
            <div style={{textAlign:'center',marginTop:12,display:'flex',gap:8,justifyContent:'center',flexWrap:'wrap'}}>
              {isOpponentUndoReq && (
                <div className="card" style={{padding:'10px 16px',display:'inline-flex',gap:8,alignItems:'center'}}>
                  <span style={{fontSize:13}}>상대가 한수 무르기를 요청했습니다</span>
                  <button className="btn btn-primary btn-sm" onClick={() => handleUndoResponse(true)}>수락</button>
                  <button className="btn btn-sell btn-sm" onClick={() => handleUndoResponse(false)}>거절</button>
                </div>
              )}
              {iMyUndoReq && (
                <span style={{fontSize:13,color:'var(--text-dim)',alignSelf:'center'}}>한수 무르기 요청 중...</span>
              )}
              {canRequestUndo && (
                <button className="btn btn-ghost" onClick={handleUndoRequest}>한수 무르기</button>
              )}
              <button className="btn btn-sell" onClick={handleResign}>기권</button>
            </div>
          )
        })()}
        {room.status === 'WAITING' && isCreator && (
          <div style={{textAlign:'center',marginTop:12}}>
            <button className="btn btn-sell" onClick={handleCancel}>방 취소</button>
          </div>
        )}
      </div>
    )
  }

  // ── List View ──
  return (
    <div>
      <div className="flex-between mb-16">
        <h2 style={{margin:0}}>♟️ 체스</h2>
        <div style={{display:'flex',gap:8}}>
          {myMmr && <span className="badge badge-blue" style={{alignSelf:'center'}}>MMR {myMmr.mmr}</span>}
          <button className="btn btn-ghost" onClick={loadLeaderboard}>{e('🏆','')} 리더보드</button>
          <button className="btn btn-ghost" onClick={loadHistory}>{e('📜','')} 전적</button>
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>+ 방 만들기</button>
        </div>
      </div>

      {showCreate && (
        <div className="card mb-16">
          <div className="card-title">방 만들기</div>
          <div style={{display:'flex',gap:8,alignItems:'center'}}>
            <input type="number" placeholder="베팅 포인트 (0=무료)" value={betAmount} onChange={e => setBetAmount(e.target.value)} style={{width:160}} />
            <button className="btn btn-primary" onClick={handleCreate}>생성</button>
            <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>취소</button>
          </div>
          <div style={{fontSize:12,color:'var(--text-dim)',marginTop:4}}>보유: {fmt(points)}P | 색상은 랜덤 배정됩니다</div>
        </div>
      )}

      {rooms.length === 0 ? (
        <div className="card" style={{textAlign:'center',color:'var(--text-dim)'}}>대기 중인 방이 없습니다</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>#</th><th>방장</th><th>상대</th><th>베팅</th><th>상태</th><th></th></tr></thead>
            <tbody>
              {rooms.map(r => (
                <tr key={r.id}>
                  <td>{r.id}</td>
                  <td>{r.creator_name}</td>
                  <td>{r.opponent_name || '-'}</td>
                  <td>{r.bet_amount > 0 ? `${fmt(r.bet_amount)}P` : '무료'}</td>
                  <td><span className={`badge ${r.status === 'PLAYING' ? 'badge-green' : 'badge-orange'}`}>{r.status === 'PLAYING' ? '진행중' : '대기중'}</span></td>
                  <td>
                    {r.status === 'WAITING' && r.creator_id !== currentUser?.user_id && (
                      <button className="btn btn-primary btn-sm" onClick={() => handleJoin(r.id)}>참가</button>
                    )}
                    {(r.creator_id === currentUser?.user_id || r.opponent_id === currentUser?.user_id) && (
                      <button className="btn btn-ghost btn-sm" onClick={() => enterRoom(r.id)}>입장</button>
                    )}
                    {r.status === 'PLAYING' && r.creator_id !== currentUser?.user_id && r.opponent_id !== currentUser?.user_id && (
                      <button className="btn btn-ghost btn-sm" onClick={() => enterRoom(r.id)}>관전</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 리더보드 모달 */}
      {showLeaderboard && (
        <div className="modal-overlay" onClick={() => setShowLeaderboard(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="flex-between mb-16">
              <h3 style={{margin:0}}>{e('🏆','')} 체스 MMR 리더보드</h3>
              <button className="btn btn-ghost" onClick={() => setShowLeaderboard(false)}>✕</button>
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>#</th><th>닉네임</th><th>MMR</th><th>승</th><th>패</th><th>무</th><th>승률</th></tr></thead>
                <tbody>
                  {leaderboard.map((r, i) => (
                    <tr key={r.user_id} className={r.user_id === currentUser?.user_id ? 'highlight-row' : ''}>
                      <td className={rankClass(i+1)}>{i+1}</td>
                      <td>{r.nickname}</td>
                      <td><strong>{r.mmr}</strong></td>
                      <td style={{color:'var(--green)'}}>{r.wins}</td>
                      <td style={{color:'var(--red)'}}>{r.losses}</td>
                      <td>{r.draws}</td>
                      <td>{r.wins + r.losses > 0 ? ((r.wins / (r.wins + r.losses)) * 100).toFixed(1) + '%' : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* 전적 모달 */}
      {showHistory && (
        <div className="modal-overlay" onClick={() => setShowHistory(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="flex-between mb-16">
              <h3 style={{margin:0}}>{e('📜','')} 체스 전적</h3>
              <button className="btn btn-ghost" onClick={() => setShowHistory(false)}>✕</button>
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>상대</th><th>결과</th><th>수순</th><th>베팅</th><th>시간</th></tr></thead>
                <tbody>
                  {history.map(r => {
                    const isWin = r.winner_id === currentUser?.user_id
                    const isDraw = !r.winner_id
                    const opponent = r.creator_id === currentUser?.user_id ? r.opponent_name : r.creator_name
                    return (
                      <tr key={r.id}>
                        <td>{opponent}</td>
                        <td style={{color: isDraw ? 'var(--text-dim)' : isWin ? 'var(--green)' : 'var(--red)', fontWeight:700}}>
                          {isDraw ? '무승부' : isWin ? '승' : '패'}
                        </td>
                        <td>{r.move_count}수</td>
                        <td>{r.bet_amount > 0 ? `${fmt(r.bet_amount)}P` : '-'}</td>
                        <td style={{fontSize:11,color:'var(--text-dim)'}}>{r.finished_at?.slice(5,16)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}


// GIFT MODAL (포인트 선물)
// ═══════════════════════════════════════════════
function GiftModal({ onClose, onSuccess }) {
  const [nickname, setNickname] = useState('')
  const [amount, setAmount] = useState('')
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)

  const handleSend = async () => {
    if (!nickname.trim()) return alert('닉네임을 입력하세요')
    const a = parseInt(amount)
    if (!a || a < 10) return alert('최소 10P부터 선물 가능합니다')
    setSending(true)
    try {
      const res = await api.sendPointGift({ to_nickname: nickname, amount: a, message: message || null })
      alert(res.message)
      onSuccess?.(res.new_balance)
      onClose()
    } catch (e) {
      alert(e.message)
    }
    setSending(false)
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={e => e.stopPropagation()}>
        <div className="flex-between mb-16">
          <div className="card-title" style={{margin:0}}>{e('🎁','')} 포인트 선물</div>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>✕</button>
        </div>
        <div className="form-group">
          <div className="form-label">받는 사람 (닉네임)</div>
          <input placeholder="닉네임 입력" value={nickname} onChange={e => setNickname(e.target.value)} />
        </div>
        <div className="form-group">
          <div className="form-label">포인트 (최소 10P)</div>
          <input type="number" placeholder="포인트" value={amount} onChange={e => setAmount(e.target.value)} />
        </div>
        <div className="form-group">
          <div className="form-label">메시지 (선택)</div>
          <input placeholder="감사합니다~" value={message} onChange={e => setMessage(e.target.value)} />
        </div>
        <button className="btn btn-primary btn-block" onClick={handleSend} disabled={sending}>
          {sending ? '전송 중...' : '선물하기'}
        </button>
      </div>
    </div>
  )
}


// ═══════════════════════════════════════════════
// SHOP (상점)
// ═══════════════════════════════════════════════
function ShopPage({ onPointsChange }) {
  const [users, setUsers] = useState([])
  const [target, setTarget] = useState('')
  const [sending, setSending] = useState(false)
  const [myBadge, setMyBadge] = useState(null)
  const [shopInfo, setShopInfo] = useState(null)
  const [msg, setMsg] = useState(null)

  useEffect(() => {
    api.getUsersList().then(setUsers).catch(() => {})
    api.getMyBadge().then(setMyBadge).catch(() => {})
    api.getShopItems().then(setShopInfo).catch(() => {})
  }, [])

  const handleBuyChicken = async () => {
    if (!target || sending) return
    setSending(true)
    try {
      const r = await api.buyChicken(target)
      setMsg({ type: 'success', text: r.message })
      onPointsChange?.()
      api.getMyBadge().then(setMyBadge).catch(() => {})
    } catch (err) {
      setMsg({ type: 'error', text: err.message })
    }
    setSending(false)
  }

  const handleRemoveChicken = async () => {
    setSending(true)
    try {
      const r = await api.removeChicken()
      setMsg({ type: 'success', text: r.message })
      onPointsChange?.()
      api.getMyBadge().then(setMyBadge).catch(() => {})
    } catch (err) {
      setMsg({ type: 'error', text: err.message })
    }
    setSending(false)
  }

  return (
    <div className="page-card">
      <h2>{e('🏪','')} 상점</h2>

      {/* 내 배지 현황 */}
      <div className="card" style={{ marginBottom: 20 }}>
        <h3>내 배지</h3>
        <div style={{ fontSize: 28, margin: '12px 0' }}>
          {myBadge?.badge || <span style={{ color: 'var(--text-dim)' }}>없음</span>}
        </div>
        {myBadge?.chickens?.length > 0 && (
          <div>
            <p style={{ fontSize: 13, color: 'var(--text-dim)', marginBottom: 8 }}>
              내 닭대가리 {myBadge.chickens.length}마리:
            </p>
            <ul style={{ fontSize: 12, color: 'var(--text-dim)', listStyle: 'none', padding: 0 }}>
              {myBadge.chickens.map((c, i) => (
                <li key={i}>{e('🐔','')} {c.sender}님이 부착 — 만료: {c.expires_at?.slice(5, 16)}</li>
              ))}
            </ul>
            <button className="btn-danger" onClick={handleRemoveChicken} disabled={sending}
              style={{ marginTop: 12 }}>
              {e('🔥','')} 닭대가리 전체 소각 ({shopInfo?.remove_chicken_cost?.toLocaleString() || '1,000'}P)
            </button>
          </div>
        )}
      </div>

      {/* 닭대가리 씌우기 */}
      <div className="card">
        <h3>{e('🐔','')} 닭대가리 씌우기</h3>
        <p style={{ fontSize: 13, color: 'var(--text-dim)', margin: '8px 0' }}>
          {shopInfo?.items?.[0]?.description || '타인 닉네임 앞에 닭대가리를 붙입니다 (24시간 유지, 최대 5마리)'}
        </p>
        <p style={{ fontSize: 14, fontWeight: 600, margin: '8px 0' }}>
          비용: {shopInfo?.items?.[0]?.cost?.toLocaleString() || '500'}P
        </p>
        <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center' }}>
          <select
            value={target}
            onChange={ev => setTarget(ev.target.value)}
            style={{
              flex: 1, padding: '8px 12px', borderRadius: 8,
              border: '1px solid var(--border)', background: 'var(--surface)',
              color: 'var(--text)', fontSize: 13
            }}
          >
            <option value="">대상 선택...</option>
            {users.map(u => (
              <option key={u.id} value={u.nickname}>{u.nickname}</option>
            ))}
          </select>
          <button className="btn-primary" onClick={handleBuyChicken} disabled={!target || sending}>
            {e('🐔','')} 씌우기!
          </button>
        </div>
      </div>

      {msg && (
        <div className={`toast toast-${msg.type}`} style={{ position: 'static', marginTop: 16 }}>
          {msg.text}
        </div>
      )}
    </div>
  )
}


// ═══════════════════════════════════════════════
// TICKER (전광판)
// ═══════════════════════════════════════════════
function Ticker() {
  const [items, setItems] = useState([])

  useEffect(() => {
    const load = async () => {
      try {
        const data = await api.getTickerMessages()
        setItems(data)
      } catch {}
    }
    load()
    const iv = setInterval(load, 10000) // 10초마다 갱신
    return () => clearInterval(iv)
  }, [])

  if (items.length === 0) return null

  const text = items.map(m => m.message).join('　　│　　')

  return (
    <div className="ticker-bar">
      <div className="ticker-track">
        <span className="ticker-content">{text}　　│　　{text}</span>
      </div>
    </div>
  )
}


// ═══════════════════════════════════════════════
// LOTTO PAGE (로또)
// ═══════════════════════════════════════════════
function LottoPage({ onPointsChange }) {
  const [status, setStatus] = useState(null)
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(true)
  const [picking, setPicking] = useState(false)
  const [countdown, setCountdown] = useState('')
  const [msg, setMsg] = useState('')

  const loadStatus = async () => {
    try {
      const data = await api.getLottoStatus()
      setStatus(data)
    } catch {}
    setLoading(false)
  }

  const loadHistory = async () => {
    try {
      const data = await api.getLottoHistory()
      setHistory(data)
    } catch {}
  }

  useEffect(() => { loadStatus(); loadHistory() }, [])

  // 카운트다운
  useEffect(() => {
    const tick = () => {
      const now = new Date()
      const target = new Date()
      target.setHours(15, 55, 0, 0)
      if (now >= target) {
        setCountdown('추첨 완료')
        return
      }
      const diff = target - now
      const h = Math.floor(diff / 3600000)
      const m = Math.floor((diff % 3600000) / 60000)
      const s = Math.floor((diff % 60000) / 1000)
      setCountdown(`${h}시간 ${m}분 ${s}초`)
    }
    tick()
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [])

  const handlePick = async (num) => {
    if (picking) return
    if (!status) return
    if (status.my_numbers.includes(num)) {
      // 이미 선택된 번호 → 취소
      setPicking(true)
      try {
        await api.deleteLottoPick(num)
        setMsg(`${num}번 취소됨`)
        await loadStatus()
      } catch (err) { setMsg(err.message) }
      setPicking(false)
      return
    }
    const remaining = status.max_tickets - status.my_numbers.length
    if (remaining <= 0) {
      setMsg(`티켓을 모두 사용했습니다 (${status.my_rank}위 → ${status.max_tickets}장)`)
      return
    }
    setPicking(true)
    try {
      await api.pickLottoNumbers([num])
      setMsg(`${num}번 선택!`)
      await loadStatus()
    } catch (err) { setMsg(err.message) }
    setPicking(false)
  }

  if (loading) return <div className="loading">로딩 중...</div>
  if (!status) return <div className="loading">로또 정보를 불러올 수 없습니다</div>

  const isDrawn = countdown === '추첨 완료'
  const lastResult = status.last_result

  return (
    <div className="lotto-page">
      {/* 풀 & 카운트다운 */}
      <div className="card lotto-pool-card">
        <div className="lotto-round">{e('🎱','')} {status.round_number}회차 로또</div>
        <div className="lotto-pool-amount">{status.pool_amount.toLocaleString()}P</div>
        <div className="lotto-countdown">
          {isDrawn ? '오늘 추첨 완료' : `추첨까지 ${countdown}`}
        </div>
        <div className="lotto-tax-info">
          매일 15:55 보유세 10% 징수 (50% 소각 / 50% 로또풀)
        </div>
        {status.tax_info && (
          <div className="lotto-tax-detail">
            오늘 징수: {status.tax_info.total_collected?.toLocaleString()}P
            (소각 {status.tax_info.burned?.toLocaleString()}P / 로또 {status.tax_info.to_lotto?.toLocaleString()}P)
          </div>
        )}
      </div>

      {/* 내 티켓 현황 */}
      <div className="card">
        <div className="card-title">
          내 티켓 (순위 {status.my_rank}위 → {status.max_tickets}장)
          <span className="lotto-ticket-count"> [{status.my_numbers.length}/{status.max_tickets}]</span>
        </div>
        {status.my_numbers.length > 0 ? (
          <div className="lotto-my-picks">
            {status.my_numbers.map(n => (
              <span key={n} className="lotto-my-num">{n}</span>
            ))}
          </div>
        ) : (
          <div style={{fontSize:13,color:'var(--text-dim)'}}>아래에서 번호를 선택하세요</div>
        )}
        {msg && <div className="mt-8" style={{fontSize:13}}>{msg}</div>}
      </div>

      {/* 번호 선택 그리드 */}
      {!isDrawn && (
        <div className="card">
          <div className="card-title">번호 선택 (1~46)</div>
          <div className="lotto-grid">
            {Array.from({length: 46}, (_, i) => i + 1).map(n => (
              <button
                key={n}
                className={`lotto-num ${status.my_numbers.includes(n) ? 'lotto-num-picked' : ''}`}
                onClick={() => handlePick(n)}
                disabled={picking}
              >{n}</button>
            ))}
          </div>
        </div>
      )}

      {/* 최근 추첨 결과 */}
      {lastResult && (
        <div className="card lotto-result-card">
          <div className="card-title">{e('🎱','')} 최근 추첨 결과</div>
          <div className="lotto-result">
            <div className="lotto-result-round">{lastResult.round_number}회</div>
            <div className="lotto-result-number">{lastResult.winning_number}</div>
            <div className="lotto-result-info">
              {lastResult.status === 'DRAWN'
                ? `당첨! ${lastResult.winner_names} (+${lastResult.payout_per_winner?.toLocaleString()}P)`
                : `당첨자 없음 — ${lastResult.pool_amount?.toLocaleString()}P 이월`
              }
            </div>
          </div>
        </div>
      )}

      {/* 히스토리 */}
      <div className="card">
        <div className="card-title">추첨 기록</div>
        {history.length === 0 ? (
          <div style={{fontSize:13,color:'var(--text-dim)'}}>아직 추첨 기록이 없습니다</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>회차</th><th>날짜</th><th>당첨번호</th><th>상금풀</th><th>당첨자</th></tr></thead>
              <tbody>
                {history.map(r => (
                  <tr key={r.round_number} className={r.status === 'DRAWN' ? 'lotto-row-won' : ''}>
                    <td>{r.round_number}</td>
                    <td>{r.draw_date}</td>
                    <td><span className="lotto-winning-num">{r.winning_number}</span></td>
                    <td className="text-right">{r.pool_amount?.toLocaleString()}P</td>
                    <td>{r.status === 'DRAWN'
                      ? `${r.winner_names} (+${r.payout_per_winner?.toLocaleString()}P)`
                      : '이월'
                    }</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}


// ═══════════════════════════════════════════════
// PATCH NOTES PAGE (패치노트)
// ═══════════════════════════════════════════════
const PATCH_NOTES = [
  {
    date: '2026-04-09',
    title: 'v1.6.0 — 관전 배팅 & 주간 보상 시스템',
    changes: [
      { tag: '신규', text: '관전 배팅 — 오목/체스 관전 시 승자 예측 배팅 가능! 적중 시 참여자끼리 배당 비례 배분' },
      { tag: '신규', text: '주간 보상 — 오목 MMR 상위 3명, 노들 주간 상위 3명에게 포인트 보상 (1등 3,000P / 2등 2,000P / 3등 1,000P)' },
      { tag: '신규', text: '노들 주간 리더보드 — 주간 풀이 수 기준 랭킹 확인 가능' },
      { tag: '신규', text: '전체 포인트 초기화 — 관리자가 모든 유저 포인트를 10,000P로 리셋 가능' },
      { tag: '삭제', text: '해피아워 시스템 완전 삭제 — 인플레이션 방지' },
    ],
  },
  {
    date: '2026-04-01',
    title: 'v1.5.0 — 로또 시스템 & 경제 밸런스 패치',
    changes: [
      { tag: '신규', text: '로또 시스템 추가 — 매일 15:55 추첨, 1~46번 중 번호 선택. 순위별 티켓 차등 지급 (1~4위 1장, 5~8위 3장, 9위~ 5장)' },
      { tag: '신규', text: '보유세 도입 — 매일 전체 유저 포인트의 10%를 징수하여 50%는 소각, 50%는 로또 상금풀로 투입합니다. 양극화 해소와 디플레이션을 위한 조치입니다' },
      { tag: '조정', text: '가위바위보 배당 1.98배 → 1.97배로 조정 — 1%가 로또 풀에 적립됩니다' },
      { tag: '조정', text: '가위바위보 잭팟 레이크 5% → 4%로 조정 — 로또 도입에 따른 레이크 재분배입니다' },
      { tag: '삭제', text: '해피아워 시스템 삭제 — 인플레이션 방지를 위해 해피아워를 완전히 제거했습니다' },
      { tag: '조정', text: '연승/연패 채팅 표기 기준을 5연승 → 10연승, 3연승(주사위) → 10연승 이상으로 변경합니다' },
      { tag: '신규', text: '채팅 관리 기능 — 관리자가 채팅 전체 초기화 및 개별 메시지 삭제가 가능합니다' },
      { tag: '개선', text: '채팅 스크롤 개선 — 채팅창을 열면 항상 최신 메시지가 바로 보이도록 수정했습니다' },
      { tag: '신규', text: '패치노트 페이지 추가 — 업데이트 히스토리를 확인할 수 있습니다' },
    ],
  },
]

function PatchNotesPage() {
  return (
    <div className="patchnotes-page">
      {PATCH_NOTES.map((patch, i) => (
        <div key={i} className="card patchnote-card">
          <div className="patchnote-header">
            <span className="patchnote-date">{patch.date}</span>
            <span className="patchnote-title">{patch.title}</span>
          </div>
          <ul className="patchnote-list">
            {patch.changes.map((c, j) => (
              <li key={j} className="patchnote-item">
                <span className={`patchnote-tag patchnote-tag-${c.tag}`}>{c.tag}</span>
                <span>{c.text}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}


// ═══════════════════════════════════════════════
// CHAT PANEL (채팅)
// ═══════════════════════════════════════════════
function ChatPanel({ visible, onClose }) {
  const chatUser = api.getUser()
  const [messages, setMessages] = useState([])
  const [lastId, setLastId] = useState(0)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const messagesEndRef = useRef(null)
  const containerRef = useRef(null)
  const shouldAutoScroll = useRef(true)

  const scrollToBottom = (instant = false) => {
    messagesEndRef.current?.scrollIntoView({ behavior: instant ? 'instant' : 'smooth' })
  }

  // 스크롤 위치 감지 — 맨 아래 근처면 auto-scroll
  const handleScroll = () => {
    const el = containerRef.current
    if (!el) return
    shouldAutoScroll.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60
  }

  // 적응형 폴링 (최근 30초 내 메시지 있으면 1초, 없으면 3초)
  const lastMsgTimeRef = useRef(Date.now())
  const pollTimerRef = useRef(null)

  useEffect(() => {
    if (!visible) return
    let cancelled = false
    const poll = async () => {
      if (cancelled) return
      try {
        const data = await api.getChatMessages(lastId)
        if (data.length > 0) {
          setMessages(prev => [...prev, ...data])
          setLastId(data[data.length - 1].id)
          lastMsgTimeRef.current = Date.now()
        }
      } catch {}
      if (cancelled) return
      const idle = Date.now() - lastMsgTimeRef.current > 30000
      pollTimerRef.current = setTimeout(poll, idle ? 3000 : 1000)
    }
    poll()
    return () => { cancelled = true; clearTimeout(pollTimerRef.current) }
  }, [visible, lastId])

  // 새 메시지 auto-scroll
  useEffect(() => {
    if (shouldAutoScroll.current) {
      requestAnimationFrame(() => scrollToBottom())
    }
  }, [messages])

  // 최초 열릴 때 맨 아래로
  useEffect(() => {
    if (visible && messages.length > 0) {
      shouldAutoScroll.current = true
      requestAnimationFrame(() => scrollToBottom(true))
    }
  }, [visible])

  const handleSend = async () => {
    const msg = input.trim()
    if (!msg || sending) return
    setSending(true)
    try {
      await api.sendChatMessage(msg)
      setInput('')
    } catch {}
    setSending(false)
  }

  const handleDeleteMsg = async (msgId) => {
    try {
      await api.adminDeleteChatMessage(msgId)
      setMessages(prev => prev.filter(m => m.id !== msgId))
    } catch {}
  }

  const handleKeyDown = (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey) {
      ev.preventDefault()
      handleSend()
    }
  }

  if (!visible) return null

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <span>{e('💬','')} 채팅</span>
        <button className="chat-close" onClick={onClose}>&times;</button>
      </div>
      <div className="chat-messages" ref={containerRef} onScroll={handleScroll}>
        {messages.map(m => (
          <div key={m.id} className={`chat-msg ${m.msg_type === 'system' ? 'chat-system' : ''}`}>
            {m.msg_type === 'user' && (
              <span className="chat-nick">{m.badge && <span className="chat-badge">{m.badge}</span>}{m.nickname}</span>
            )}
            <span className="chat-text">{m.message}</span>
            <span className="chat-time">{m.created_at?.slice(11, 16)}</span>
            {chatUser?.is_admin && <button className="chat-delete" onClick={() => handleDeleteMsg(m.id)} title="삭제">&times;</button>}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>
      <div className="chat-input-area">
        <input
          className="chat-input"
          value={input}
          onChange={ev => setInput(ev.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="메시지 입력..."
          maxLength={200}
        />
        <button className="chat-send" onClick={handleSend} disabled={sending}>전송</button>
      </div>
    </div>
  )
}


// ═══════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════
export default function App() {
  const [loggedIn, setLoggedIn] = useState(!!api.getUser())
  const [tab, setTab] = useState(getTabFromHash)
  const [userPoints, setUserPoints] = useState(null)
  const [toast, setToast] = useState(null)
  const [showGift, setShowGift] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [chatHidden, setChatHidden] = useState(() => localStorage.getItem('sa_chat_hidden') === 'true')
  const [theme, setTheme] = useState(() => localStorage.getItem('sa-theme') || 'default')

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('sa-theme', theme)
  }, [theme])

  const THEMES = [
    { id: 'default', label: '🌙 다크' },
    { id: 'excel', label: 'Excel' },
    { id: 'finance', label: '🏦 금융' },
  ]
  const cycleTheme = () => {
    const idx = THEMES.findIndex(t => t.id === theme)
    setTheme(THEMES[(idx + 1) % THEMES.length].id)
  }
  const toggleChatHidden = () => {
    setChatHidden(prev => {
      const next = !prev
      localStorage.setItem('sa_chat_hidden', String(next))
      if (next) setChatOpen(false)
      return next
    })
  }
  const user = api.getUser()

  const refreshPoints = useCallback(() => {
    api.getPoints().then(r => setUserPoints(r.points)).catch(() => {})
  }, [])

  const showToast = useCallback((msg, type = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }, [])

  // 로그인 후 출석 체크 + 포인트 로드
  useEffect(() => {
    if (!loggedIn) return
    refreshPoints()
    api.checkAttendance().then(r => {
      if (r.checked_in) {
        showToast(`출석 체크! +${r.points_awarded}P 적립 ${e('🎉','')}`)
        setUserPoints(r.total_points)
      }
    }).catch(() => {})
    // 구제 포인트: 100P 이하일 때 자동 200P 지급
    api.claimRelief().then(r => {
      if (r.relief) {
        showToast(`구제 포인트 +${r.points_awarded}P 지급!`)
        setUserPoints(r.points)
      }
    }).catch(() => {})
  }, [loggedIn])

  // 브라우저 뒤로가기/앞으로가기 지원
  useEffect(() => {
    const onPop = () => setTab(getTabFromHash())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  // 탭 변경 시 URL 해시 업데이트
  const changeTab = useCallback((newTab) => {
    setTab(newTab)
    window.history.pushState(null, '', '#' + newTab)
  }, [])

  const handleLogout = () => {
    api.clearAuth()
    window.history.replaceState(null, '', '#login')
    setLoggedIn(false)
  }

  const handleLogin = () => {
    setLoggedIn(true)
    window.history.replaceState(null, '', '#dashboard')
    setTab('dashboard')
  }

  if (!loggedIn) return <LoginPage onLogin={handleLogin} />

  const tabs = [
    { id: 'dashboard', label: `${e('📊','')} 대시보드` },
    { id: 'trade', label: `${e('💹','')} 매매` },
    { id: 'rankings', label: `${e('🏆','')} 랭킹` },
    { id: 'board', label: `${e('📝','')} 게시판` },
    { id: 'picks', label: `${e('🎯','')} 방's pick` },
    { id: 'betting', label: `${e('🎲','')} 베팅` },
    { id: 'rps', label: `${e('✊','')} 가위바위보` },
    { id: 'dice', label: `${e('🎲','')} 주사위` },
    { id: 'gacha', label: `${e('🎰','')} 가챠` },
    { id: 'nordle', label: `${e('🔢','')} 노들` },
    { id: 'omok', label: `${e('⚫','')} 오목` },
    { id: 'chess', label: `♟️ 체스` },
    { id: 'shop', label: `${e('🏪','')} 상점` },
  ]
  if (user?.is_admin) tabs.push({ id: 'admin', label: `${e('⚙️','')} 관리` })

  const renderPage = () => {
    switch (tab) {
      case 'dashboard': return <DashboardPage />
      case 'trade': return <TradePage />
      case 'rankings': return <RankingsPage />
      case 'board': return <BoardPage onPointsChange={refreshPoints} />
      case 'picks': return <PicksPage />
      case 'betting': return <BettingPage onPointsChange={refreshPoints} />
      case 'rps': return <RPSPage onPointsChange={refreshPoints} />
      case 'dice': return <DicePage onPointsChange={refreshPoints} />
      case 'gacha': return <GachaPage onPointsChange={refreshPoints} />
      case 'nordle': return <NordlePage />
      case 'omok': return <OmokPage onPointsChange={refreshPoints} />
      case 'chess': return <ChessPage onPointsChange={refreshPoints} />
      case 'shop': return <ShopPage onPointsChange={refreshPoints} />
      case 'admin': return <AdminPage />
      default: return <DashboardPage />
    }
  }

  return (
    <div className="app-shell">
      <div className="topbar">
        <div className="topbar-logo">KIWOOM <span>v1.0</span></div>
        <div className="topbar-user">
          <span className="nick">{user?.nickname}</span>
          {userPoints !== null && (
            <span className="points" onClick={() => setShowGift(true)} title="클릭하여 포인트 선물">
              {e('🎲','[P]')} {fmt(userPoints)} P
            </span>
          )}
          <button className="btn-free-charge" onClick={async () => {
            try {
              const r = await api.claimDailyFree();
              setUserPoints(r.points);
              showToast(`출석 룰렛! +${r.reward}P ${r.reward >= 1000 ? '🎉 대박!' : ''}`);
            } catch (err) {
              showToast(err.message, 'error');
            }
          }}>{e('🎡','')} 출석룰렛</button>
          <button className="btn-chat-toggle" onClick={toggleChatHidden} title={chatHidden ? '채팅 켜기' : '채팅 끄기'}>
            {chatHidden ? `${e('💬','')} OFF` : `${e('💬','')} ON`}
          </button>
          <button className="btn-theme" onClick={cycleTheme} title="테마 변경">
            {THEMES.find(t => t.id === theme)?.label}
          </button>
          <button className="btn-logout" onClick={handleLogout}>로그아웃</button>
        </div>
      </div>
      <div className="tab-bar">
        {tabs.map(t => (
          <button key={t.id} className={`tab-item ${tab === t.id ? 'active' : ''}`}
            onClick={() => changeTab(t.id)}>{t.label}</button>
        ))}
      </div>
      <Ticker />
      <div className="main-content">
        {renderPage()}
      </div>
      {toast && <div className={`toast toast-${toast.type}`}>{toast.msg}</div>}
      {showGift && <GiftModal onClose={() => setShowGift(false)} onSuccess={(bal) => { setUserPoints(bal); showToast('선물 완료!') }} />}
      {!chatHidden && (
        <>
          <ChatPanel visible={chatOpen} onClose={() => setChatOpen(false)} />
          {!chatOpen && (
            <button className="chat-toggle" onClick={() => setChatOpen(true)} title="채팅 열기">
              {e('💬','Chat')}
            </button>
          )}
        </>
      )}
    </div>
  )
}
