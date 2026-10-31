package com.meuapp.segundatela

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.TextView

/**
 * Tela inicial: escolhe USB ou Wi-Fi e abre a tela espelhada.
 * O painel do PC abre esta activity com extras (host, port, auto=true) para conectar sozinho.
 */
class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (intent.getBooleanExtra("auto", false)) {
            open(intent.getStringExtra("host") ?: "127.0.0.1", intent.getIntExtra("port", 7777))
        }
        setContentView(R.layout.activity_main)

        val prefs = getPreferences(MODE_PRIVATE)
        val usb = findViewById<RadioButton>(R.id.usb)
        val wifi = findViewById<RadioButton>(R.id.wifi)
        val host = findViewById<EditText>(R.id.host)
        val port = findViewById<EditText>(R.id.port)
        val help = findViewById<TextView>(R.id.help)

        host.setText(prefs.getString("wifiHost", ""))
        port.setText(prefs.getInt("port", 7777).toString())

        fun showMode(isWifi: Boolean) {
            host.visibility = if (isWifi) View.VISIBLE else View.GONE
            help.setText(if (isWifi) R.string.help_wifi else R.string.help_usb)
        }
        (if (prefs.getBoolean("wifi", false)) wifi else usb).isChecked = true
        showMode(wifi.isChecked)
        findViewById<RadioGroup>(R.id.mode).setOnCheckedChangeListener { _, id -> showMode(id == R.id.wifi) }

        findViewById<Button>(R.id.connect).setOnClickListener {
            val p = port.text.toString().toIntOrNull()
            if (p == null || p !in 1..65535) {
                port.error = "Porta inválida"
                return@setOnClickListener
            }
            val wifiHost = host.text.toString().trim()
            if (wifi.isChecked && wifiHost.isEmpty()) {
                host.error = "Digite o IP do PC"
                return@setOnClickListener
            }
            prefs.edit()
                .putBoolean("wifi", wifi.isChecked)
                .putString("wifiHost", wifiHost)
                .putInt("port", p)
                .apply()
            open(if (wifi.isChecked) wifiHost else "127.0.0.1", p)
        }
    }

    private fun open(host: String, port: Int) = startActivity(
        Intent(this, DisplayActivity::class.java).putExtra("host", host).putExtra("port", port)
    )
}
