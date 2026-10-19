//! Гліфи, яких Атанор ще не виконує: розбір їх не пропускає (програма йде до еталона).
use crate::interp::*;
use crate::lexer::Pos;
use crate::value::V;

pub fn prim(_it: &mut Interp, g: char, _a: &[V], pos: Pos) -> R<V> {
    fatal(format!("гліф «{}» Атанор не виконує (мав піти до еталона)", g), Some(pos))
}
