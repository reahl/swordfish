from reahl.ptongue import GemstoneError


class GemstoneDebugActionOutcome:
    def __init__(self, has_completed, result=None):
        self.has_completed = has_completed
        self.result = result


class GemstoneStackFrame:
    def __init__(self, gemstone_process, level):
        self.gemstone_session = gemstone_process.session
        self.gemstone_process = gemstone_process
        self.level = level
        self.frame_data = frame_data = self.gemstone_process.perform(
            '_frameContentsAt:',
            self.gemstone_session.from_py(self.level),
        )
        self.is_valid = not frame_data.isNil().to_py
        if self.is_valid:
            self.gemstone_method = frame_data.at(1)
            self.ip_offset = frame_data.at(2)
            self.var_context = frame_data.at(4)

    @property
    def step_point_offset(self):
        # AI: See OGStackFrame initializeContexts.
        step_point = self.gemstone_method.perform(
            '_nextStepPointForIp:',
            self.ip_offset,
        )
        offsets = self.gemstone_method.perform('_sourceOffsets')
        offset = offsets.at(step_point.min(offsets.size()))
        return offset.to_py

    @property
    def method_source(self):
        return self.gemstone_method.fullSource().to_py

    @property
    def method_name(self):
        return self.gemstone_method.selector().to_py

    @property
    def class_name(self):
        return self.gemstone_method.homeMethod().inClass().asString().to_py

    @property
    def self(self):
        return self.frame_data.at(8)

    @property
    def vars(self):
        frame_vars = {}
        var_names = self.frame_data.at(9)
        for index, name in enumerate(var_names):
            value = self.frame_data.at(11 + index)
            frame_vars[name.to_py] = value
        return frame_vars


class GemstoneCallStack:
    def __init__(self, gemstone_process):
        self.gemstone_process = gemstone_process
        self.frames = self.make_frames()

    def make_frames(self):
        max_level = self.gemstone_process.stackDepth().to_py
        stack = []
        level = 1
        while level <= max_level:
            frame = self.stack_frame(level)
            if frame.is_valid:
                stack.append(frame)
                level += 1
            else:
                level = max_level + 1
        return stack

    def stack_frame(self, level):
        return GemstoneStackFrame(self.gemstone_process, level)

    def __getitem__(self, level):
        return self.frames[level - 1]

    def __iter__(self):
        return iter(self.frames)

    def __bool__(self):
        return bool(self.frames)


class GemstoneDebugSession:
    def __init__(self, exception):
        self.exception = exception

    def call_stack(self):
        if self.exception is None or self.exception.context is None:
            return []
        return GemstoneCallStack(self.exception.context)

    def continue_running(self):
        return self.debug_action_outcome(self.continued_result)

    def continued_result(self):
        result = self.exception.continue_with()
        result.gemstone_class().asString()
        return result

    def step_over(self, level):
        return self.debug_action_outcome_for_level(level, self.step_over_result)

    def step_over_result(self, level):
        return self.exception.context.gciStepOverFromLevel(level)

    def step_into(self, level):
        return self.debug_action_outcome_for_level(level, self.step_into_result)

    def step_into_result(self, level):
        return self.exception.context.gciStepIntoFromLevel(level)

    def step_through(self, level):
        return self.debug_action_outcome_for_level(level, self.step_through_result)

    def step_through_result(self, level):
        return self.exception.context.gciStepThruFromLevel(level)

    def stop(self):
        return self.debug_action_outcome(self.stop_result)

    def stop_result(self):
        return self.exception.context.resume()

    def debug_action_outcome_for_level(self, level, action):
        return self.debug_action_outcome(lambda: action(level))

    def debug_action_outcome(self, action):
        try:
            result = action()
            return GemstoneDebugActionOutcome(True, result=result)
        except GemstoneError as error:
            self.exception = error
            return GemstoneDebugActionOutcome(False)
