import { useEffect, useRef, useState } from 'react'

function buildSocketUrl(urlBase, sessionId, scenario) {
    const base = (urlBase || window.location.origin).trim() || window.location.origin
    const withProtocol = base.startsWith('http://') || base.startsWith('https://')
        ? base
        : `http://${base}`

    const wsBase = withProtocol
        .replace('http://', 'ws://')
        .replace('https://', 'wss://')

    return `${wsBase}/ws/session/${encodeURIComponent(sessionId)}?scenario=${encodeURIComponent(scenario)}`
}

export function useSessionSocket({ sessionId, scenario, urlBase }) {
    const socketRef = useRef(null)
    const [lines, setLines] = useState([])
    const [connected, setConnected] = useState(false)

    useEffect(() => {
        const socketUrl = buildSocketUrl(urlBase, sessionId, scenario)
        let socket

        try {
            socket = new WebSocket(socketUrl)
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            setLines((prev) => [...prev, `\n[WebSocket Error] ${message}\n`])
            setConnected(false)
            return () => { }
        }

        socketRef.current = socket

        socket.onopen = () => setConnected(true)
        socket.onclose = () => setConnected(false)
        socket.onerror = () => {
            setLines((prev) => [...prev, '\n[WebSocket Error] Could not connect to backend.\n'])
        }

        socket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data)
                if (data.type === 'stdout' || data.type === 'stderr' || data.type === 'meta') {
                    setLines((prev) => [...prev, data.payload])
                }
            } catch {
                setLines((prev) => [...prev, String(event.data)])
            }
        }

        return () => {
            if (socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ type: 'shutdown' }))
            }
            socket.close()
        }
    }, [scenario, sessionId, urlBase])

    const sendCommand = (text) => {
        const socket = socketRef.current
        if (!socket || socket.readyState !== WebSocket.OPEN) {
            return
        }
        socket.send(JSON.stringify({ type: 'input', payload: text }))
    }

    return { lines, connected, sendCommand }
}
