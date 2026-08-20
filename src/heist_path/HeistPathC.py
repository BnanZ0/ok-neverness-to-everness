import re

from src.heist_path.HeistPathB import HeistPathB


class HeistPathC(HeistPathB):
    """路径3: 使用残虹作为避战角色, 更加安全"""
    def run_path(self):
        self.goto_lg1_skip_Cankou()
        self.wait_team_ui_settle()
        self.switch_to_runner(check_switched=True)
        self.lg1_wp1_safer()
        self.lg1_wp2()
        self.lg1_wp3()
        self.lg1_wp4_buster()
        self.lg1_wp5_Cankou()
        self.lg2_wp1_to_exit1_Cankou()
        self.lg2_wp1_remains_Cankou()
        self.lg2_wp2_to_exit2_Cankou()   
        self.lg2_wp3_to_layzer_room()
        self.lg2_wp3_in_layzer_room()
        self.lg2_wp4()
        if self.exit_state[1]:
            self.lg2_wp4_to_exit1()
        elif self.exit_state[2]:
            self.lg2_wp4_to_exit2()
        else:
            self.lg2_wp4_to_exit3()

    def goto_lg1_skip_Cankou(self):
        self.log_round_info("残虹、大厅前往LG1")
        self.sleep(0.30)
        self.switch_to_avoider(check_switched=True)
        self.send_key_down("w")
        self.sleep(0.35)
        self.send_key_down("shift")
        self.sleep(0.28)
        self.send_key_up("shift")
        self.sleep(0.32)
        self.send_key_down("shift")
        self.sleep(0.5)
        self.send_key_up("shift")
        self.sleep(1.61)
        self.send_key('d', down_time=2.68, after_sleep=0.28) 
        self.send_key('a', down_time=0.40) 
        self.send_key_up('w')
        self.send_key('w', down_time=0.04, after_sleep=1.00) 
        self.wait_and_interact(direction="w", is_lock=True, time_out=6.4)
        self.send_key('g', down_time=0.12, after_sleep=1.32)
        self.start_interaction_watch()
        self.send_key_down("f")  # start pick         
        self.send_key_down('w', after_sleep=0.86) 
        self.send_key('d', down_time=0.13, after_sleep=1.64)
        self.send_key('space', down_time=0.24)
        self.stop_interaction_watch()
        self.send_key_up("f")
        self.sleep(1.64)
        self.wait_and_interact(direction="w", is_lock=True, time_out=5.2) 
        self.send_key_down('w', after_sleep=0.32)
        self.send_key_down('d', after_sleep=0.19)
        self.send_key('shift', down_time=0.22, after_sleep=0.92)
        self.send_key_up('d') 
        self.send_key_down('a', after_sleep=0.61) 
        self.send_key_up('w', after_sleep=0.85) 
        self.send_key('shift', down_time=0.17, after_sleep=1.90) 
        self.send_key_down('s')
        self.send_key_up('a', after_sleep=1.86) 
        self.send_key_down('d', after_sleep=0.13) 
        self.send_key_up('s', after_sleep=2.42) 
        self.send_key_up('d')
        self.send_key_down('w', after_sleep=0.71) 
        self.send_key_down('a', after_sleep=0.13) 
        self.send_key_up('w', after_sleep=0.48)
        self.send_key_up('a', after_sleep=0.37) 
        self.send_key('d', down_time=0.13, after_sleep=0.41) 
        self.send_key('s', down_time=0.06, after_sleep=0.83) 
        self.click(0.50, 0.50, key="middle", down_time=0.15)
        self.send_key('g', down_time=0.08, after_sleep=1.33) 
        self.send_key_down('w', after_sleep=0.31) 
        self.send_key('shift', down_time=0.20, after_sleep=1.08) 
        self.send_key('shift', down_time=1.06, after_sleep=0.40) 
        self.send_key_up("w")
        self.sleep(0.1)
        self.send_key_down("d")
        self.wait_and_interact(direction="d", is_lock=True, time_out=3.2) 
        if self.find_interac():
            self.clear_current_combat()
            self.sleep(0.20)
            self.send_key('a', down_time=2.32, after_sleep=0.35) # press key 'a'
            self.send_key_down('w', after_sleep=1.08) # key down 'w'
            self.send_key('a', down_time=0.63, after_sleep=0.30) # press key 'a'
            self.send_key_up('w', after_sleep=0.84) # key up 'w'
            self.send_key('d', down_time=2.07, after_sleep=0.16) # press key 'd'
            if self.wait_ocr(x=0.55, y=0.48, to_x=0.75, to_y=0.61, match=re.compile("开门"), time_out=1.14):
                self.sleep(0.20)
                self.send_key("f",down_time=0.01)
                self.sleep(0.20)
                self.send_key_down("a")
                self.sleep(0.15)
                self.send_key_up("a")
                self.send_key_down("w")
                self.wait_and_interact(direction="w", is_lock=False,time_out=5.0 )
            else:
                 from src.tasks.AutoHeistTask import AbortException
                 raise AbortException("路径中断")                

        self.send_key_down("a")
        self.sleep(0.2)
        self.send_key_down("w")
        self.sleep(0.2)
        self.send_key_up("a")
        self.wait_and_interact(direction="w", is_lock=True, time_out=5.2)
        self.sleep(2.00)

    def lg1_wp5_Cankou(self):
        self.log_round_info("LG1 WP5 残虹 开始避战路线")

        self.switch_to_avoider(check_switched=True)
        self.sleep(0.50)
        self.perform_avoidance_action()
        self.sleep(0.10)
        self.send_key_down("w")
        self.sleep(1.00)
        self.send_key_down("shift")
        self.sleep(0.3)
        self.send_key_up("shift")
        self.sleep(0.30)
        self.wait_and_interact(direction="a", is_lock=True, time_out=5.2)
        self.sleep(0.10)
        self.send_key_down("w")
        self.sleep(0.30)
        self.wait_and_interact(direction="w")       

    def lg2_wp1_to_exit1_Cankou(self):
        self.log_round_info("“残虹、隐身到撤离点1”")
        #使用残虹隐身搜藏品层大厅，极度安全
        self.sleep(0.53)
        self.send_key_down('w')
        self.sleep(5.15)
        self.send_key_up('w')
        self.send_key_down("g")
        self.sleep(0.1)
        self.send_key_up("g")
        self.sleep(0.3)
        self.send_key_down('a')
        self.send_key_up('w')
        self.sleep(0.2)
        self.send_key_down("f") #start pick
        self.sleep(4.52)
        self.send_key_up('a')
        self.sleep(0.31)
        self.send_key_down('s')
        self.sleep(0.98)
        self.send_key_up("s")
        self.sleep(0.33)
        self.send_key_down('d')
        self.sleep(0.66)
        self.send_key_down('w')
        self.sleep(1.00) 
        self.send_key_up('d')
        self.sleep(1.86)
        self.send_key_up('w')
        self.sleep(0.19)
        self.send_key_down('d') 
        self.sleep(0.79)
        self.send_key_down('w') 
        self.send_key_up('d')
        self.sleep(0.56)
        self.send_key_up('w')
        self.sleep(0.19) 
        self.send_key_down('d')
        self.sleep(0.62)
        self.send_key_up("d")
        self.send_key('s', down_time=0.74) 
        self.send_key_down('d')
        self.sleep(0.52)
        self.send_key_up("d")
        self.sleep(0.11)
        self.send_key_up("f") #end pick
        self.send_key_down("w")
        self.sleep(0.5)
        self.exit_state[1] = self.try_open_exit(direction="w")
        self.sleep(0.5)

    def lg2_wp1_remains_Cankou(self):
        self.log_round_info("残虹、lg2_wp1_remains_Cankou")
        self.send_key('w', down_time=1.39) 
        self.send_key('a', down_time=0.71, after_sleep=0.18) 
        self.send_key_down('s', after_sleep=0.85) # key down 's'
        self.send_key_down('a') # key down 'a'
        self.send_key_up('s', after_sleep=0.43) # key up 's'
        self.send_key_down('s', after_sleep=0.27) # key down 's'
        self.send_key_up('a', after_sleep=0.39) # key up 'a'
        self.send_key_up('s', after_sleep=0.59) # key up 's'
        self.start_interaction_watch()
        self.send_key_down("f")
        self.send_key('g', down_time=0.09, after_sleep=1.27) # press key 'g'
        self.send_key('d', down_time=0.48, after_sleep=0.18) # press key 'd'
        self.send_key('w', down_time=2.08) # press key 'w'
        self.send_key_down('a', after_sleep=0.79) # key down 'a'
        self.send_key_down('w', after_sleep=0.40) # key down 'w'
        self.send_key_up('a', after_sleep=0.40) # key up 'a'
        self.send_key('a', down_time=0.29, after_sleep=1.11) # press key 'a'
        self.send_key_up('w', after_sleep=1.87) # key up 'w'
        self.send_key('d', down_time=1.67) # press key 'd'
        self.send_key_down('w', after_sleep=0.30) # key down 'w'
        self.send_key('d', down_time=0.32, after_sleep=0.61) # press key 'd'
        self.send_key_down('d', after_sleep=0.19) # key down 'd'
        self.send_key_up('w', after_sleep=0.92) # key up 'w'
        self.send_key_up("f")
        self.send_key_up('d') 
        self.send_key_down("f")
        self.send_key_down('s', after_sleep=6.13) # key down 's'
        self.send_key_down('d') # key down 'd'
        self.send_key_up('s', after_sleep=4.04) # key up 's'
        self.send_key_up('d') # key up 'd'
        self.send_key('d', down_time=0.05, after_sleep=0.32) # press key 'd'
        self.send_key('d', down_time=0.09, after_sleep=1.63) # press key 'd'
        self.send_key_down("f")
        self.send_key('g', down_time=0.09, after_sleep=1.53) # press key 'g'
        self.loot_safes_while_walking(
            direction="w", min_walk_time=0.20, time_out=0.64, hold=False, send_pick=True
        )  

        self.send_key_down('w', after_sleep=0.13) 
        self.send_key('space', down_time=0.14, after_sleep=0.18) # press key 'space'
        self.send_key('space', down_time=0.17, after_sleep=2.17) # press key 'space'
        self.send_key('a',down_time=0.10)
        self.send_key('space', down_time=0.13, after_sleep=0.27) # press key 'space'
        self.send_key('space', down_time=0.13, after_sleep=1.65) # press key 'space'
        self.send_key_up('w') # key up 'w'
        self.send_key('d', down_time=1.74, after_sleep=0.24) # press key 'd'
        self.send_key('s', down_time=0.55, after_sleep=0.17) # press key 's'
        self.send_key_down('d', after_sleep=0.75) # key down 'd'
        self.send_key_down('s') # key down 's'
        self.send_key_up('d', after_sleep=0.87) # key up 'd'
        self.send_key_up('s') # key up 's'
        self.send_key('a', down_time=0.52) # press key 'a'
        self.send_key('s', down_time=6.69) # press key 's'
        self.send_key_down('d', after_sleep=0.89) # key down 'd'
        self.send_key_down('w', after_sleep=0.13) # key down 'w'
        self.send_key_up('d', after_sleep=1.57) # key up 'd'
        self.send_key_up('w') # key up 'w'
        self.send_key('d', down_time=0.83) # press key 'd'
        self.send_key_down('w', after_sleep=0.63) # key down 'w'
        self.send_key_down('d') # key down 'd'
        self.send_key_up('w', after_sleep=0.38) # key up 'w'
        self.send_key_down('w') # key down 'w'
        self.send_key_up('d', after_sleep=0.99) # key up 'd'
        self.send_key_up('w') # key up 'w'
        self.send_key('d', down_time=0.46, after_sleep=0.11) # press key 'd'
        self.send_key('w', down_time=0.70, after_sleep=1.36) # press key 'w'
        self.send_key_up("f") #end pick
        self.stop_interaction_watch()
        
    def lg2_wp2_to_exit2_Cankou(self):
        self.log_round_info("残虹、藏品层小房间")
        self.sleep(0.5)
        self.send_key('g', down_time=0.08, after_sleep=0.42)
        self.send_key('s', down_time=1.12, after_sleep=0.82) # press key 's'
        self.send_key('d', down_time=1.41, after_sleep=0.21) # press key 'd'
        self.send_key_down('w', after_sleep=1.76) # key down 'w'
        self.send_key_down('d') # key down 'd'
        self.send_key_up('w', after_sleep=3.21) # key up 'w'
        self.send_key_up('d') # key up 'd'
        self.send_key('s', down_time=0.49) # press key 's'
        self.send_key('d', down_time=0.53) # press key 'd'
        self.send_key('w', down_time=2.66) 
        self.start_interaction_watch()
        self.send_key_down("f")# press key 'w'
        self.send_key('d', down_time=0.86, after_sleep=0.14) # press key 'd'
        self.send_key('w', down_time=0.41) # press key 'w'
        self.send_key('a', down_time=1.09, after_sleep=0.13) # press key 'a'
        self.send_key('w', down_time=0.45) # press key 'w'
        self.send_key('d', down_time=0.67, after_sleep=0.34) # press key 'd'
        self.send_key('w', down_time=1.63, after_sleep=2.53) # press key 'w'
        self.send_key('g', down_time=0.10, after_sleep=3.49) # press key 'g'
        self.send_key('d', down_time=1.18, after_sleep=0.31) # press key 'd'
        self.send_key('d', down_time=0.28, after_sleep=0.27) # press key 'd'
        self.send_key('w', down_time=2.34, after_sleep=0.22) # press key 'w'
        self.send_key('a', down_time=0.17, after_sleep=0.37) # press key 'a'
        self.send_key('s', down_time=1.80, after_sleep=0.94) # press key 's'
        self.send_key('f', down_time=0.09, after_sleep=0.69) # press key 'f'
        self.send_key('d', down_time=1.07, after_sleep=0.23) # press key 'd'
        self.send_key('d', down_time=0.15, after_sleep=0.14) # press key 'd'
        self.send_key('s', down_time=0.64, after_sleep=2.47) # press key 's
        self.send_key_up("f") #end pick
        self.log_round_info("薄荷、前往撤离点2")
        self.stop_interaction_watch()
        self.switch_to_runner(check_switched=True)
        self.sleep(0.11)
        self.send_key_down("w")
        self.sleep(0.56)
        self.send_key_up("f")  # end pick
        self.sleep(2.00)
        self.send_key_down("a")
        self.sleep(0.40)
        self.send_key_up("a")
        self.sleep(1.57)
        self.exit_state[2] = self.try_open_exit(direction="w")
        self.sleep(0.40)