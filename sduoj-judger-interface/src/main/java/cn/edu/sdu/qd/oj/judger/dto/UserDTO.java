package cn.edu.sdu.qd.oj.judger.dto;

import lombok.*;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class UserDTO extends BaseDTO {
   private String username;
   private String password;
}
