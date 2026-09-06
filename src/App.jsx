import './App.css'

const featureCards = [
  {
    title: 'Smart Recommendations',
    description: 'AI analyzes your mood, watch history, and favorite genres to suggest films you actually want to watch.',
  },
  {
    title: 'Mood Matching',
    description: 'Pick your vibe—dark thriller, cozy comedy, or cinematic epic—and get a shortlist in seconds.',
  },
  {
    title: 'Movie Night Planner',
    description: 'Build the perfect watchlist for a date night, family movie night, or a solo binge session.',
  },
]

const trendingMovies = [
  { title: 'Neon Horizon', rating: '8.9', tag: 'Sci‑Fi' },
  { title: 'Midnight Echo', rating: '8.7', tag: 'Thriller' },
  { title: 'Velvet Run', rating: '9.1', tag: 'Drama' },
  { title: 'Sunset Circuit', rating: '8.5', tag: 'Action' },
]

function App() {
  return (
    <div className="page-shell">
      <header className="topbar">
        <div className="brand-wrap">
          <div className="brand-mark">C</div>
          <span>CineStream AI</span>
        </div>

        <nav className="nav" aria-label="Main navigation">
          <a href="#discover">Discover</a>
          <a href="#features">Features</a>
          <a href="#trending">Trending</a>
        </nav>

        <button type="button" className="primary-button small-button">
          Sign in
        </button>
      </header>

      <main className="hero-section" id="discover">
        <div className="copy-column">
          <span className="eyebrow">AI-powered cinema</span>
          <h1>Find your next favorite movie in minutes.</h1>
          <p>
            CineStream AI blends your taste, trending titles, and cinematic mood
            signals to suggest unforgettable films for every night.
          </p>

          <div className="cta-row">
            <button type="button" className="primary-button">
              Start watching
            </button>
            <button type="button" className="secondary-button">
              Browse library
            </button>
          </div>

          <ul className="stats-list" aria-label="Platform stats">
            <li>
              <strong>1.2M+</strong>
              <span>Titles indexed</span>
            </li>
            <li>
              <strong>94%</strong>
              <span>Match accuracy</span>
            </li>
            <li>
              <strong>24/7</strong>
              <span>Recommendations</span>
            </li>
          </ul>
        </div>

        <div className="visual-column" aria-label="Featured film preview">
          <div className="poster-card poster-main">
            <div className="poster-overlay">
              <span className="badge">Featured</span>
              <h2>Echoes of Tomorrow</h2>
              <p>Mind-bending sci-fi • 2h 14m</p>
            </div>
          </div>

          <div className="mini-panel">
            <div>
              <span className="mini-label">Tonight</span>
              <strong>Best Match</strong>
            </div>
            <span className="score">9.4</span>
          </div>
        </div>
      </main>

      <section className="features" id="features">
        <div className="section-heading">
          <span className="eyebrow">Why CineStream AI</span>
          <h3>Built for movie lovers who want better picks.</h3>
        </div>

        <div className="feature-grid">
          {featureCards.map((feature) => (
            <article key={feature.title} className="feature-card">
              <div className="feature-icon" aria-hidden="true">
                ✦
              </div>
              <h4>{feature.title}</h4>
              <p>{feature.description}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="trending" id="trending">
        <div className="section-heading inline-heading">
          <span className="eyebrow">Trending now</span>
          <a href="#discover">View all</a>
        </div>

        <div className="movie-list">
          {trendingMovies.map((movie) => (
            <article key={movie.title} className="movie-item">
              <div className="movie-art" aria-hidden="true">
                <span>{movie.tag}</span>
              </div>
              <div className="movie-meta">
                <h4>{movie.title}</h4>
                <div className="movie-row">
                  <span>{movie.tag}</span>
                  <strong>{movie.rating}</strong>
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  )
}

export default App
