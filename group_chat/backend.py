from abc import ABC, abstractmethod
import anthropic



class GroupAgent(ABC):
    def __init__(self, name, description):
        self.name = name
        self.description = description

    @abstractmethod
    def generate(messages):
        pass

    @abstractmethod
    def stream_generate(messages):
        pass

    @abstractmethod
    def get_specs(self):
        pass



class GroupChat:
    def __init__(self, agents, messages=[]):
        self.agents = agents
        self.messages = messages

    def append_message(self, name, content):
        role = 'user' if name == '用户' else 'assistant'
        content = f'{name}：{content}'
        self.messages.append({'role':role, 'content':content})


    def reset(self):
        self.messages = []


class GroupChat:
    def __init__(self, agents, messages=[]):
        self.agents = agents
        self.messages = messages

    def append_message(self, name, content):
        self.messages.append({'role':name, 'content':content})


    def get_transcript(self):
        transcript = ""
        for message in self.messages:
            transcript += f"{message['role']}: {message['content']}\n"

        return transcript


    def reset(self):
        self.messages = []




class ClaudeGroupManager(GroupAgent):
    def __init__(self, client, name, description, group_chat):
        super().__init__(name, description)
        self.group_chat = group_chat
        self.client = client
        self.agent_specs = [agent.get_specs() for agent in group_chat.agents]
        self.agent_specs_str = "\n".join([f"名称：{spec['name']}, 角色：{spec['description']}" for spec in self.agent_specs])

        self.system_prompt = f"""你是一个针对养宠用户创建的群聊的群主兼管理员。群中包含不同的为用户服务的AI宠物助手以及真人兽医。以下是所有群聊内AI助手的信息：
                                {self.agent_specs_str}

                                作为整个群聊的大脑和指挥官，你的职责是根据对话历史和用户输入，判断接下来由哪一些AI助手发言，确定发言顺序。请遵循以下要求：
                                1. 请你根据用户或其他助手的输入，以及每一个AI助手的角色能力，合理地选择进行回答的AI。AI的能力必须能解决当前群聊讨论的问题，或者能够起到辅助性质的作用。
                                2. 在合理的情况下，可以让多个助手发言，以增强群组的讨论度和交互感。
                                4. 注意规避重复性和不必要的发言安排。例如，当提供安慰的助手发言后，应当视情况让他等几轮在发言，又或者，提供额外信息支持的助手应当在有必要向他寻求信息的时候再安排发言，等等。
                                5. 要仔细考虑好发言的顺序安排。例如，如果需要专业问诊助手进行问诊，那么提供信息和情报资讯的助手应当先发言，用于辅助专业问诊助手回答，同时也能让问诊助手在最后直接对用户追问。其他顺序逻辑请你自己多加思考。
                                5. 使用JSON格式输出你的判断。

                                """ \
                                + \
                                """
                                示例JSON输出：
                                <json>[{'名称':'...', '发言顺序':'1'}, {'名称':'...', '发言顺序':'2'}, ...]</json>
                                """



    def generate(self, messages):

        response = self.client.messages.create(
            model="claude-3-7-sonnet-20250219",
            max_tokens=2048,
            system=self.system_prompt,
            messages=messages
        )

        response_message = response.content[0].text
        json_output = eval(response_message[response_message.find("<json>")+6:response_message.find("</json>")])

        return json_output

    def stream_generate(self, messages):
        pass

    def get_specs(self):
        return {
            "name": self.name,
            "description": self.description,
        }




# Generic group agent with tools
class ClaudeGroupAgent(GroupAgent):
    def __init__(self, client, name, description, system_prompt, model='claude-3-7-sonnet-20250219', tools=None, thinking=False):
        super().__init__(name, description)
        self.system_prompt = system_prompt
        self.client = client
        self.model = model
        self.thinking = thinking
        self.tools = tools

    def generate(self, messages):
        if self.thinking:

            thinking_message = ""
            response_message = ""

            response = self.client.messages.create(
                model=self.model,
                system=self.system_prompt,
                max_tokens=8096,
                thinking={
                    "type": "enabled",
                    "budget_tokens": 1024
                },
                messages=messages,
                #tools=self.tools
            )
            
            for block in response.content:
                  if block.type == 'thinking':
                      thinking_message += block.thinking
                  elif block.type == 'text':
                      response_message += block.text

            combined_message = "<think>" + thinking_message + "</think>" + "\n" + response_message
            return combined_message

        elif self.tools:

            response_message = ""
            func_name = None
            func_args = None
            func_return = None
            tool_use_id = None

            tool_response = self.client.messages.create(
                model=self.model,
                system=self.system_prompt,
                max_tokens=8096,
                messages=messages,
                tools=self.tools
            )

            #print(tool_response)

            for block in tool_response.content:
                  if block.type == 'tool_use':
                      func_name = block.name
                      func_args = block.input
                      tool_use_id = block.id
                      func_return = eval(func_name)(**func_args)
                      #print(func_return)

                  elif block.type == 'text':
                      response_message += block.text

            if func_name:          

                tooled_messages = messages + \
                    [{'role':'assistant', 
                      'content':[
                          {
                          "type": "tool_use",
                          "id": tool_use_id,
                          "name": func_name,
                          "input": func_args
                          }
                      ]
                      },
                      {"role": "user",
                        "content": [

                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": f'{func_return}'
                            }
                        ]
                      }]
                second_response = self.client.messages.create(
                    model=self.model,
                    system=self.system_prompt,
                    max_tokens=8096,
                    messages=tooled_messages,
                    tools=self.tools
                )
                #print(second_response)

                response_message += second_response.content[0].text

            return response_message


        else:
            response = self.client.messages.create(
                model=self.model,
                system=self.system_prompt,
                max_tokens=8096,
                messages=messages,
                #tools=self.tools
            )
            response_message = response.content[0].text

            return response_message

    def stream_generate(self, messages):

        response = client.client.messages.create(
            model=self.model,
            system=self.system_prompt,
            messages=messages,
            #tools=self.tools,
            stream=True
        )

        for chunk in response:
            yield chunk.choices[0].delta.content

    def get_specs(self):
        return {
            "name": self.name,
            "description": self.description,
        }



pet_collar_tools=[
    {
        "name": "get_collar_data",
        "description": "获取智能项圈记录的宠物活动数据，可调整获取的数据天数",
        "input_schema": {
            "type": "object",
            "properties": {
                "pet_name": {
                    "type": "string",
                    "description": "宠物的名字",
                },
                "num_days": {
                    "type": "number",
                    "description": "需要获取的回看数据天数。最大值为30天",
                }
            },
            "required": ["pet_name", "num_days"],
        },
    }
]




group_chat_prompt = "注：你现在处在一个为养宠用户量身定制的群聊当中，群聊中有不同的AI助手和真人为用户进行宠物相关的服务。请你结合群聊历史对话和输入，执行对应的回复，并模拟群聊的聊天模式（如可以使用 @某人 或emoji这样的行为）。"

agent_specs = [{'name': "网络情报专家",
                'description':"一个能够连接互联网的专业的情报搜集专家，可以查看、收集、并总结互联网上的各类资讯，对用户的咨询和其他成员的回答提供帮助。",
                'system_prompt':f"""你是一个能够连接互联网的专业的情报搜集专家，会针对用户的提问或者需求，查看、收集、并总结互联网上的各类资讯，并将搜索内容精确地呈现出来。
                                   {group_chat_prompt}""",
                'model':"claude-3-7-sonnet-20250219", 'tools':None},
               {'name': "智能硬件管家",
                'description':"一个专门负责管理用户家中各种宠物智能设备的管家，能够获取到所有设备记录的宠物各方面行为体征信息，并对这些信息作总结分析，为群聊讨论提供帮助。",
                'system_prompt':f"""一个专门负责管理用户家中各种宠物智能设备的管家，能够获取到所有设备记录的宠物各方面行为体征信息，还能对这些信息作总结分析，并将这些信息和总结提供出来帮助他人。
                                   {group_chat_prompt}""",
                'model':"claude-3-7-sonnet-20250219", 'tools':pet_collar_tools},

               {'name': "专业临床医生",
                'description':"一个经验丰富，专注于专业问诊诊断的临床宠物兽医，可以进行缜密思考并通过多轮反问来帮助确诊宠物疾病。",
                'system_prompt':f"""你是一个经验丰富，专注于专业问诊诊断的临床宠物兽医，可以进行缜密思考并通过多轮反问来帮助确诊宠物疾病。在回答前会进行深度思考。
                                   然后针对用户提出的宠物疾病诊断方面的需求，你会结合历史信息按照如下步骤做出分析：
                                   1. 给出三个最有可能的疾病，并对每一个疾病严密分析，为什么已知症状关联到这三个疾病。
                                   2. 对这三个疾病分别给出概率，总和要为100。
                                   3. 最后判断当前信息是否足够给出诊断。如果不足，则向用户提出1-2个追问问题，继续问诊。如果足够，则给出诊断。

                                   你的问诊输出格式应当如下：
                                   「症状分析」
                                   1. 。。。
                                   2. 。。。
                                   3. 。。。
                                   「疾病关联概率」
                                   1. 。。。
                                   2. 。。。
                                   3. 。。。
                                   此处给出追问问题或诊断结果。


                                   除此之外，对于其他非问诊相关的宠物医疗相关的专业问题，你可以直接给出解答，不需要执行这三个问诊步骤。
                                   {group_chat_prompt}
                                   """,

                'model':"claude-3-7-sonnet-20250219", 'tools':None, 'thinking':True},
               {'name': "温柔体贴小助理",
                'description':"一个温柔的小助理，擅长解决用户的情绪问题，提供各类负面情绪的疏导以及安慰。同时还能对其他成员的回复进行赞赏，捧哏等活跃气氛的行为。",
                'system_prompt':f"""你是一个温柔的小助理，擅长解决用户的情绪问题，提供各类负面情绪的疏导以及安慰。同时还能对其他成员的回复进行赞赏，捧哏等活跃气氛的行为。但是注意！说的话应保持简短。
                                 {group_chat_prompt}""",
                'model':"claude-3-7-sonnet-20250219", 'tools':None},
               {'name': "群聊守护者",
                'description':"一个专门回怼用户不当请求、与宠物完全无关的请求、以及找茬行为的高手。擅长应对某些言语恶劣用户或者不合理的请求。",
                'system_prompt':f"""你是一个专门回怼用户不当请求、与宠物完全无关的请求、以及找茬行为的高手。擅长应对某些言语恶劣用户或者不合理的请求。会用犀利的语言拒绝或回怼用户。
                                   {group_chat_prompt}""",
                'model':"claude-3-7-sonnet-20250219", 'tools':None},

               {'name': "视觉分析师",
                'description':"一个可以看到图片和视频的视觉分析师，擅长分析各种图片视频的内容，并依据内容给出相应的回答或是内容总结。",
                'system_prompt':"",
                'model':"claude-3-7-sonnet-20250219", 'tools':None},
               {'name': "硬件数据管家",
                'description':"一个可以获取到用户宠物的智能设备数据的管家，可以提供用户接入的各类宠物智能设备数据，以及生成初步的总结报告。",
                'system_prompt':"",
                'model':"claude-3-7-sonnet-20250219", 'tools':None}
               ]


#agent1 = GLMGroupAgent("网络情报专家", "一个会联网搜索的专业助手。", "回答前请深度思考。", glm_client, model='glm-4-plus', tools=tools)
