import random
import asyncio
from pipeline.vlm.vlm_scheduler import BatchScheduler
import json

class ProjectGenerator:
    def __init__(self, args=None):

        self.args = args
        self.project_id = None
        self.lock = asyncio.Lock()
        self.project = None
            
    async def generate_project(self, task_set: dict, num: int, app_name: str = "Slack"):
        
        try:
            self.project_id = task_set.get("id")
        except:
            exit()
        
        sub_task = None
        setup_flag = False
        
        if task_set.get('setup_task'):
            setup = task_set.get('setup_task')

            if setup.startswith("(Setup)"):
                sub_task = setup.replace("(Setup)", f"(Setup) In {app_name},", 1)
            else:
                sub_task = f"In {app_name}, " + setup

            sub_task += '\n\nThe following steps describe how to perform the setup task.'
            sub_task += '\nThe Setup Task Steps Require:'
            for text in task_set.get('setup_steps'):
                sub_task += '\n'+text

        if task_set.get('main_task'):
            main_task = f"In {app_name}, " + task_set.get('main_task')
            main_inst = main_task
            main_task += '\n\nThe following steps describe how to perform the main task.'
            main_task += '\n\nThe Main Task Steps Require:'

            main_rag = main_inst + "\n\n" + (task_set.get("relevant_procedure") or "")
            for text in task_set.get('main_steps'):
                main_task += '\n'+text
        
        if self.args.with_step and self.args.rag:
            raise ValueError("Cannot use both --with_step and --rag flags at the same time. Please choose one.")

        if self.args.with_step:
            if sub_task is not None:
                task = [(sub_task,sub_task), (main_task,main_inst)]
                setup_flag = True
            else:
                task = [(main_task,main_inst)]

        elif self.args.rag:
            if sub_task is not None:
                task = [(sub_task,sub_task), (main_rag,main_inst)]
                setup_flag = True
            else:
                task = [(main_rag,main_inst)]

        else:
            if sub_task is not None:
                task = [(sub_task,sub_task), (main_inst,main_inst)]
                setup_flag = True
            else:
                task = [(main_inst,main_inst)]

        
        # print(f"[ProjectGenerator] Generated project {self.project_id}: {main_task[:50]}...")
        # print(f"[ProjectGenerator] Setup flag: {setup_flag}")
        for (i, j) in task:
            print("==== real input ====")
            print(i)
            print("==== instruction ====")
            print(j)
            print("====================")

        return task, self.project_id, setup_flag