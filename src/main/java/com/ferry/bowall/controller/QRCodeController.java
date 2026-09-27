package com.ferry.bowall.controller;
import com.ferry.bowall.common.QRCodeGenerator;
import com.google.zxing.WriterException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.awt.*;
import java.io.IOException;

@RestController
@RequestMapping("/qrcode")
@Slf4j
public class QRCodeController {
    @Autowired
    private final QRCodeGenerator qrCodeGenerator;

    public QRCodeController(QRCodeGenerator qrCodeGenerator) {
        this.qrCodeGenerator = qrCodeGenerator;
    }

    @GetMapping("/{text}")
    public ResponseEntity<String> generateBase64QRCode(@PathVariable String text) {
        try {
            String base64QRCode = qrCodeGenerator.generateBase64QRCode(text, 500, 500);
            System.out.println("===========QRcode================");
            return ResponseEntity.ok(base64QRCode);
        } catch (WriterException | IOException e) {
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body("Error generating QR code");
        }
    }
}