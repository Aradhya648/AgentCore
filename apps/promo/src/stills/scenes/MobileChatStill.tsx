import { AssistantContent } from "@mobile/components/AssistantView";
import { fold } from "@mobile/protocol/fold";
import type { SSEEvent } from "@agentcore/contract-types";
import { Folder, Menu, SquarePen } from "lucide-react";
import { useMemo } from "react";
import { AbsoluteFill } from "remotion";
import {
  MOBILE_FANOUT_EVENTS,
  MOBILE_FANOUT_USER_TEXT,
} from "../data/mobileFanoutEvents";


/*
 * 9:20 mobile chat still for 宣传图 #8. Real mobile ChatPage chrome + AssistantContent /
 * TeamView driven by a truncated fan-out conformance-style SSE vector (mobile fold).
 */

export const MOBILE_W = 1080;
export const MOBILE_H = Math.round((MOBILE_W * 20) / 9);
export const MOBILE_LOGICAL_W = 390;
export const MOBILE_SCALE = MOBILE_W / MOBILE_LOGICAL_W;
export const MOBILE_LOGICAL_H = MOBILE_H / MOBILE_SCALE;

function projectTurn(events: SSEEvent[]) {
  const p = fold(events);
  const isMulti = p.runs.length > 0;
  return {
    ...p,
    team: isMulti
      ? { agents: p.agents, runs: p.runs, progress: p.progress }
      : undefined,
  };
}

export function MobileChatStill() {
  const turn = useMemo(() => projectTurn(MOBILE_FANOUT_EVENTS), []);

  return (
    <AbsoluteFill>
      <div className="promo-mobile-still-root">
        <div
          className="promo-mobile-still-scale"
          style={{
            width: MOBILE_LOGICAL_W,
            height: MOBILE_LOGICAL_H,
            transform: `scale(${MOBILE_SCALE})`,
          }}
        >
          <div className="screen promo-mobile-chat-screen">
            <header className="bar">
              <span className="link icon-btn" aria-hidden>
                <Menu size={20} />
              </span>
              <span className="bar-title">对话</span>
              <div className="bar-right">
                <span className="link icon-btn" aria-hidden>
                  <Folder size={20} />
                </span>
                <span className="link icon-btn" aria-hidden>
                  <SquarePen size={20} />
                </span>
              </div>
            </header>

            <div className="messages">
              <div className="bubble user">{MOBILE_FANOUT_USER_TEXT}</div>
              <div className="turn">
                <div className="bubble assistant">
                  <AssistantContent
                    process={turn.process}
                    content={turn.content}
                    reasoning={turn.reasoning}
                    citations={turn.citations}
                    captainContext={turn.captainContext}
                    team={turn.team}
                  />
                </div>
              </div>
            </div>

            <div className="composer">
              <button type="button" className="attach-btn" aria-hidden>
                ＋
              </button>
              <input readOnly placeholder="说点什么…" value="" aria-hidden />
              <button type="button" className="stop">
                停止
              </button>
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
}
