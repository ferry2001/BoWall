package com.ferry.bowall.service;

import com.baomidou.mybatisplus.spring.service.IService;
import com.ferry.bowall.entity.Fans;


public interface FansService extends IService<Fans> {

    Fans isfan(String account, String fansAccount);
}
