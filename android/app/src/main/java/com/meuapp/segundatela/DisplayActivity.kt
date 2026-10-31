package com.meuapp.segundatela

import android.app.Activity
import android.graphics.Color
import android.media.MediaCodec
import android.media.MediaFormat
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.MotionEvent
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.View
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.Toast
import java.io.BufferedInputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.Executors
import kotlin.math.min

/**
 * Mostra a tela do PC (vídeo H.264 decodificado pelo chip de vídeo do tablet) e devolve os toques.
 *
 * Protocolo (TCP, big-endian):
 *   PC -> tablet: ["H264"][int32 largura][int32 altura], depois [int32 tamanho][quadro H.264] repetido
 *   tablet -> PC: [byte ação 0=down 1=move 2=up | dedo 0-9 << 4][float x][float y], x/y de 0 a 1
 *                 [byte 3][0f][0f] = quadro mostrado (o PC segura o próximo se já houver 2 a caminho)
 */
class DisplayActivity : Activity(), SurfaceHolder.Callback {
    private lateinit var surface: SurfaceView
    private val sender = Executors.newSingleThreadExecutor()
    @Volatile private var running = false
    @Volatile private var socket: Socket? = null
    @Volatile private var out: DataOutputStream? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        surface = SurfaceView(this)
        surface.holder.addCallback(this)
        setContentView(FrameLayout(this).apply {
            setBackgroundColor(Color.BLACK)
            addView(surface, FrameLayout.LayoutParams(-1, -1, Gravity.CENTER))
        })
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        @Suppress("DEPRECATION")
        if (hasFocus) window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or
            View.SYSTEM_UI_FLAG_FULLSCREEN or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
            View.SYSTEM_UI_FLAG_LAYOUT_STABLE or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
            View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
    }

    override fun surfaceCreated(holder: SurfaceHolder) {
        if (running) return  // a tela só mudou de tamanho; a conexão continua
        running = true
        val host = intent.getStringExtra("host") ?: "127.0.0.1"
        val port = intent.getIntExtra("port", 7777)
        Thread({ receive(host, port) }, "receiver").start()
    }

    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) = Unit

    override fun surfaceDestroyed(holder: SurfaceHolder) {
        running = false
        runCatching { socket?.close() }
    }

    override fun onDestroy() {
        super.onDestroy()
        sender.shutdownNow()
    }

    private fun receive(host: String, port: Int) {
        var codec: MediaCodec? = null
        try {
            Socket().use { s ->
                s.tcpNoDelay = true
                s.connect(InetSocketAddress(host, port), 5000)
                socket = s
                out = DataOutputStream(s.getOutputStream())
                val input = DataInputStream(BufferedInputStream(s.getInputStream(), 1 shl 16))
                val magic = ByteArray(4).also { input.readFully(it) }
                if (String(magic) != "H264") error("atualize o Segunda Tela no PC")
                val w = input.readInt()
                val h = input.readInt()
                runOnUiThread { fit(w, h) }
                codec = decoder(w, h).also { c -> Thread({ show(c) }, "show").start() }
                var buf = ByteArray(1 shl 20)
                var pts = 0L
                while (running) {
                    val n = input.readInt()
                    if (n <= 0 || n > 16 shl 20) error("quadro inválido ($n bytes)")
                    if (buf.size < n) buf = ByteArray(n)
                    input.readFully(buf, 0, n)
                    var i: Int
                    do i = codec!!.dequeueInputBuffer(100_000) while (i < 0 && running)
                    if (i < 0) break
                    codec!!.getInputBuffer(i)!!.apply { clear(); put(buf, 0, n) }
                    codec!!.queueInputBuffer(i, 0, n, pts, 0)
                    pts += 16_666
                }
            }
        } catch (e: Exception) {
            if (running) runOnUiThread {
                Toast.makeText(this, "Conexão perdida: ${e.message}", Toast.LENGTH_LONG).show()
                finish()
            }
        } finally {
            running = false
            runCatching { codec?.stop() }
            runCatching { codec?.release() }
        }
    }

    /** Decodificador de hardware desenhando direto na tela, no modo de menor atraso. */
    private fun decoder(w: Int, h: Int): MediaCodec {
        val mime = MediaFormat.MIMETYPE_VIDEO_AVC
        val format = MediaFormat.createVideoFormat(mime, w, h).apply {
            setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 4 shl 20)
            setInteger(MediaFormat.KEY_PRIORITY, 0)  // tempo real
            if (Build.VERSION.SDK_INT >= 30) setInteger(MediaFormat.KEY_LOW_LATENCY, 1)
        }
        val codec = MediaCodec.createDecoderByType(mime)
        try {
            codec.configure(format, surface.holder.surface, null, 0)
        } catch (e: Exception) {  // decodificador que recusa o modo de baixo atraso
            codec.reset()
            if (Build.VERSION.SDK_INT >= 30) format.removeKey(MediaFormat.KEY_LOW_LATENCY)
            codec.configure(format, surface.holder.surface, null, 0)
        }
        codec.start()
        return codec
    }

    /** Mostra cada quadro assim que sai do decodificador e avisa o PC. */
    private fun show(codec: MediaCodec) {
        val info = MediaCodec.BufferInfo()
        try {
            while (running) {
                val i = codec.dequeueOutputBuffer(info, 100_000)
                if (i >= 0) {
                    codec.releaseOutputBuffer(i, true)
                    send(3, 0f, 0f)
                }
            }
        } catch (_: IllegalStateException) {
            // decodificador fechado: fim da conexão
        }
    }

    /** Ajusta a área do vídeo à proporção da tela do PC (barras pretas se não bater). */
    private fun fit(w: Int, h: Int) {
        val parent = surface.parent as View
        val scale = min(parent.width / w.toFloat(), parent.height / h.toFloat())
        surface.layoutParams = FrameLayout.LayoutParams((w * scale).toInt(), (h * scale).toInt(), Gravity.CENTER)
    }

    private fun send(action: Int, x: Float, y: Float) {
        sender.execute {
            runCatching { out?.apply { writeByte(action); writeFloat(x); writeFloat(y); flush() } }
        }
    }

    /** Todos os dedos: no PC viram toque de verdade (multitoque), sem mexer no mouse. */
    override fun onTouchEvent(e: MotionEvent): Boolean {
        val v = surface
        if (v.width <= 0) return true
        fun finger(i: Int, kind: Int) {
            val id = e.getPointerId(i) % 10  // dedo vai nos 4 bits de cima da ação
            val x = ((e.getX(i) - v.left) / v.width).coerceIn(0f, 1f)
            val y = ((e.getY(i) - v.top) / v.height).coerceIn(0f, 1f)
            send(kind or (id shl 4), x, y)
        }
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN, MotionEvent.ACTION_POINTER_DOWN -> finger(e.actionIndex, 0)
            MotionEvent.ACTION_MOVE -> for (i in 0 until e.pointerCount) finger(i, 1)
            MotionEvent.ACTION_UP, MotionEvent.ACTION_POINTER_UP -> finger(e.actionIndex, 2)
            MotionEvent.ACTION_CANCEL -> for (i in 0 until e.pointerCount) finger(i, 2)
        }
        return true
    }
}
