'use client';

import { AnimatePresence, type HTMLMotionProps, motion } from 'motion/react';
import { type ReceivedChatMessage } from '@livekit/components-react';
import { ChatEntry } from '@/components/livekit/chat-entry';

const MotionContainer = motion.create('div');
const MotionChatEntry = motion.create(ChatEntry);

const CONTAINER_MOTION_PROPS = {
  variants: {
    hidden: {
      opacity: 0,
      transition: {
        ease: 'easeOut',
        duration: 0.3,
        staggerChildren: 0.1,
        staggerDirection: -1,
      },
    },
    visible: {
      opacity: 1,
      transition: {
        delay: 0.2,
        ease: 'easeOut',
        duration: 0.3,
        stagerDelay: 0.2,
        staggerChildren: 0.1,
        staggerDirection: 1,
      },
    },
  },
  initial: 'hidden',
  animate: 'visible',
  exit: 'hidden',
};

const MESSAGE_MOTION_PROPS = {
  variants: {
    hidden: {
      opacity: 0,
      translateY: 10,
    },
    visible: {
      opacity: 1,
      translateY: 0,
    },
  },
};

interface ChatTranscriptProps {
  hidden?: boolean;
  messages?: ReceivedChatMessage[];
}

export function ChatTranscript({
  hidden = false,
  messages = [],
  ...props
}: ChatTranscriptProps & Omit<HTMLMotionProps<'div'>, 'ref'>) {
  return (
    <AnimatePresence>
      {!hidden && (
        <MotionContainer
          // Fix: spread CONTAINER_MOTION_PROPS, but override the "ease" prop in-place to let it accept expected types.
          {...{
            ...CONTAINER_MOTION_PROPS,
            variants: {
              ...CONTAINER_MOTION_PROPS.variants,
              hidden: {
                ...CONTAINER_MOTION_PROPS.variants.hidden,
                transition: {
                  ...CONTAINER_MOTION_PROPS.variants.hidden.transition,
                  ease: [0.42, 0, 0.58, 1] // equivalent to 'easeOut' as Easing array
                }
              },
              visible: {
                ...CONTAINER_MOTION_PROPS.variants.visible,
                transition: {
                  ...CONTAINER_MOTION_PROPS.variants.visible.transition,
                  ease: [0.42, 0, 0.58, 1] // equivalent to 'easeOut' as Easing array
                }
              },
            }
          }}
          {...props}
        >
        
          {messages.map((msg: ReceivedChatMessage) => {
            const { id, timestamp, from, message, editTimestamp } = msg;
            const locale = typeof navigator !== "undefined" && navigator.language
              ? navigator.language
              : 'en-US';
            const messageOrigin = from?.isLocal ? 'local' : 'remote';
            const hasBeenEdited = Boolean(editTimestamp);

            return (
              <MotionChatEntry
                key={id}
                locale={locale}
                timestamp={timestamp}
                message={message}
                messageOrigin={messageOrigin}
                hasBeenEdited={hasBeenEdited}
                {...MESSAGE_MOTION_PROPS}
              />
            );
          })}
        </MotionContainer>
      )}
    </AnimatePresence>
  );
}
