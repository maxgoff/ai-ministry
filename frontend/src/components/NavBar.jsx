import './NavBar.css';

export default function NavBar({ currentPage, onPageChange }) {
  return (
    <nav className="navbar">
      <button
        className={`nav-tab ${currentPage === 'ministry' ? 'active' : ''}`}
        onClick={() => onPageChange('ministry')}
      >
        Ministry
      </button>
      <button
        className={`nav-tab ${currentPage === 'trading' ? 'active' : ''}`}
        onClick={() => onPageChange('trading')}
      >
        Trading
      </button>
    </nav>
  );
}
