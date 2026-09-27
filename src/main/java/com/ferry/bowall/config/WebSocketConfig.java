package com.ferry.bowall.config;


import com.fasterxml.jackson.databind.ObjectMapper;
import com.ferry.bowall.entity.Message;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketHandler;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import java.util.HashMap;
import java.util.Map;

@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {
    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(myHandler(), "/myWebSocket").setAllowedOrigins("*");
    }

    // Bean for WebSocket handler
    public WebSocketHandler myHandler() {
        return new MyWebSocketHandler();
    }
}


class MyWebSocketHandler extends TextWebSocketHandler {
    final private Map<String, WebSocketSession> sessionPool = new HashMap<>();

    @Override
    public void afterConnectionEstablished(WebSocketSession session) {

    }

    @Override
    protected void handleTextMessage(WebSocketSession session,@RequestBody TextMessage message) throws Exception {
        String payload = message.getPayload();
        ObjectMapper objectMapper = new ObjectMapper();
        Message msg = objectMapper.readValue(payload, Message.class);


        //when connect socket save self of session then break
        if (msg.getRecipientAccount().equals("") & msg.getContent().equals("")) {
            sessionPool.put(msg.getSenderAccount(), session);
            System.out.println("connecting");
            return;
        }

        sessionPool.put(msg.getSenderAccount(), session);

        WebSocketSession recipientSession = sessionPool.get(msg.getRecipientAccount());
        if(recipientSession != null) {
            //here is output code
            recipientSession.sendMessage(message);
            System.out.println(recipientSession);
        }else {
            System.out.println("is null");
        }
        System.out.println(sessionPool);


    }
}
