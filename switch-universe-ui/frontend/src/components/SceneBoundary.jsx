import React from 'react'

export default class SceneBoundary extends React.Component {
    constructor(props) {
        super(props)
        this.state = { hasError: false }
    }

    static getDerivedStateFromError() {
        return { hasError: true }
    }

    componentDidCatch() {
        this.setState({ hasError: true })
    }

    render() {
        if (this.state.hasError) {
            return (
                <div className="scene-fallback">
                    3D scene failed to load. Terminal remains available below.
                </div>
            )
        }

        return this.props.children
    }
}
