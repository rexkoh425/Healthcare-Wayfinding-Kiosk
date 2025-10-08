/*********
  Rui Santos & Sara Santos - Random Nerd Tutorials
  Complete project details at https://RandomNerdTutorials.com/esp32-async-web-server-espasyncwebserver-library/
  The above copyright notice and this permission notice shall be included in all
  copies or substantial portions of the Software.
*********/

// Import required libraries
#include <WiFi.h>
#include <AsyncTCP.h>
#include <ESPAsyncWebServer.h>

#include <M5Unified.h>
#include <M5GFX.h>
#include "UNIT_UHF_RFID.h"

#define OnBoardLED 2

// Replace with your network credentials
const char* ssid = "edic";
const char* password = "ttbrouter";

const char* PARAM_INPUT_1 = "output";
const char* PARAM_INPUT_2 = "state";


Unit_UHF_RFID uhf;
String info = "";

// Create AsyncWebServer object on port 80
AsyncWebServer server(80);


void setup() {
  Serial.begin(115200);
  uhf.begin(&Serial2, 115200, 16, 17, false);
  while (1) {
      info = uhf.getVersion();
      if (info != "ERROR") {
          Serial.println(info);
          break;
      }
      Serial.println("Hola");
  }
  uhf.setTxPower(500);
  
  pinMode(OnBoardLED, OUTPUT);
  // Connect to Wi-Fi
  WiFi.begin(ssid, password);
  Serial.println("Connecting to WiFi..");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.println(".");
  }
  digitalWrite(OnBoardLED, HIGH);
  

  // Print ESP Local IP Address
  Serial.println(WiFi.localIP());

  // Route for root / web page
  server.on("/", HTTP_GET, [](AsyncWebServerRequest *request){
    int read_count = 0;
    String prev_epc = "";
    while (read_count < 3) {
      Serial.print("Polling"); 
      uint8_t result = uhf.pollingOnce();
      if (result > 0) {
        for (uint8_t i = 0; i < result; i++) {
          Serial.println("pc: " + uhf.cards[i].pc_str);
          Serial.println("rssi: " + uhf.cards[i].rssi_str);
          Serial.println("epc: " + uhf.cards[i].epc_str);
          Serial.println("-----------------");
          delay(10);
        }
        if (uhf.cards[0].epc_str == prev_epc) {
          read_count += 1;
        } else {
          read_count = 1;
          prev_epc = uhf.cards[0].epc_str;
        }
        Serial.println("Read Count: " + String(read_count) + " EPC: " + uhf.cards[0].epc_str);
      }
      delay(400);
    }
    
    request->send(200, "text/plain", prev_epc.c_str());
  });

  // Start server
  server.begin();

}


void connectWiFi() {
  WiFi.begin(ssid, password);
  Serial.println("Connecting");
  while(WiFi.status() != WL_CONNECTED) {
    delay(200);
    Serial.print(".");
  }
  digitalWrite(OnBoardLED, HIGH);

  Serial.println("");
  Serial.print("Connected to WiFi network with IP Address: ");
  Serial.println(WiFi.localIP());
}

void loop() {
  // put your main code here, to run repeatedly:
  if (WiFi.status() != WL_CONNECTED) {
    digitalWrite(OnBoardLED, LOW);
    connectWiFi();
  }
  delay(5000); // check every 5 seconds 
}
