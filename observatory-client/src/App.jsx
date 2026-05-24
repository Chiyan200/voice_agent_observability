import { useState } from 'react'
import reactLogo from './assets/react.svg'
import viteLogo from './assets/vite.svg'
import heroImg from './assets/hero.png'
import './App.css'

function App() {
  const [count, setCount] = useState(0)

  return (
    <>
      <section id="center">
        <h1 className="text-3xl font-bold underline text-blue-600/100">
        Hello world!
      </h1>
      </section>

    
    </>
  )
}

export default App
