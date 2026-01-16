import React from 'react'
import Map from './components/Map'

function App() {
    return (
        <div style={{ width: '100vw', height: '100vh', display: 'flex', flexDirection: 'column' }}>
            <header style={{ padding: '1rem', background: '#333', color: 'white' }}>
                <h1>Nav MAS Admin</h1>
            </header>
            <main style={{ flex: 1, position: 'relative' }}>
                <Map />
            </main>
        </div>
    )
}

export default App
