import SwitchScene from './components/SwitchScene'
import TerminalPanel from './components/TerminalPanel'
import SceneBoundary from './components/SceneBoundary'
import { useSessionSocket } from './lib/useSessionSocket'

const apiBase = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'

export default function App() {
    const { lines, connected, sendCommand } = useSessionSocket({
        sessionId: 'demo-user',
        scenario: 'default_lab',
        urlBase: apiBase,
    })

    return (
        <main className="app-shell">
            <section className="scene-panel">
                <h1>Switch Universe</h1>
                <p>Immersive switch interaction MVP: 3D view + live CLI bridge.</p>
                <div className="scene-wrap">
                    <SceneBoundary>
                        <SwitchScene />
                    </SceneBoundary>
                </div>
            </section>
            <TerminalPanel lines={lines} connected={connected} onSend={sendCommand} />
        </main>
    )
}
