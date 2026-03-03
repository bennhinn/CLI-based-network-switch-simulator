import { useEffect, useRef, useState } from 'react'

export default function TerminalPanel({ lines, connected, onSend }) {
    const [input, setInput] = useState('')
    const outputRef = useRef(null)

    useEffect(() => {
        if (outputRef.current) {
            outputRef.current.scrollTop = outputRef.current.scrollHeight
        }
    }, [lines])

    const submit = (event) => {
        event.preventDefault()
        if (!input.trim()) {
            return
        }
        onSend(input)
        setInput('')
    }

    return (
        <section className="terminal-card">
            <header className="terminal-header">
                <span>CLI Session</span>
                <span className={connected ? 'status status-on' : 'status status-off'}>
                    {connected ? 'Connected' : 'Disconnected'}
                </span>
            </header>

            <pre ref={outputRef} className="terminal-output">
                {lines.length ? lines.join('') : 'Waiting for simulator output...'}
            </pre>

            <form onSubmit={submit} className="terminal-form">
                <input
                    value={input}
                    onChange={(event) => setInput(event.target.value)}
                    className="terminal-input"
                    placeholder="Type command, e.g. show mac address-table"
                />
                <button type="submit" className="terminal-button">Send</button>
            </form>
        </section>
    )
}
