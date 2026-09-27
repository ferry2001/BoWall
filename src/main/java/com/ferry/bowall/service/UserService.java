package com.ferry.bowall.service;

import com.baomidou.mybatisplus.spring.service.IService;
import com.ferry.bowall.entity.User;

import java.util.List;
import java.util.Map;
import java.util.Set;

public interface UserService extends IService<User> {
    void updateUser(User user);
    List<User> getUserList();

    List<User> friends(String account);

    void addFanAndFollowUser(String account, String fansAccount);

    void deleteFanAndFollowUser(String account, String fansAccount);

    User getUser(String account);

    String getUserName(String account);

    String getUserAvatar(String account);

    List<User> getUsers(Set<String> accounts);
}
