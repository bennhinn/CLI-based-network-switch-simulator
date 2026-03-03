import { Canvas } from '@react-three/fiber'
import { OrbitControls, Html } from '@react-three/drei'

function SwitchModel() {
    return (
        <group>
            <mesh position={[0, 0, 0]} castShadow receiveShadow>
                <boxGeometry args={[5, 0.8, 2.5]} />
                <meshStandardMaterial color="#253043" />
            </mesh>

            {Array.from({ length: 12 }).map((_, index) => {
                const col = index % 6
                const row = Math.floor(index / 6)
                return (
                    <mesh
                        key={index}
                        position={[-1.8 + col * 0.7, 0.45, -0.6 + row * 1.2]}
                        castShadow
                    >
                        <boxGeometry args={[0.36, 0.08, 0.25]} />
                        <meshStandardMaterial color="#14b8a6" />
                    </mesh>
                )
            })}

            <Html position={[0, 1, 0]}>
                <div style={{ color: 'white', fontSize: 12, fontFamily: 'sans-serif' }}>Switch Universe (MVP)</div>
            </Html>
        </group>
    )
}

export default function SwitchScene() {
    return (
        <Canvas shadows camera={{ position: [6, 4, 6], fov: 45 }}>
            <color attach="background" args={["#0b1020"]} />
            <ambientLight intensity={0.4} />
            <directionalLight position={[8, 8, 8]} intensity={1.2} castShadow />
            <SwitchModel />
            <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1, 0]} receiveShadow>
                <planeGeometry args={[20, 20]} />
                <meshStandardMaterial color="#111827" />
            </mesh>
            <OrbitControls enablePan enableZoom enableRotate />
        </Canvas>
    )
}
