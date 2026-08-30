package faults
import"errors"
type Class string
const(Conflict Class="conflict";Unavailable Class="unavailable";Internal Class="internal")
type Fault struct{Class Class;Cause error};func(f Fault)Error()string{return string(f.Class)};func(f Fault)Unwrap()error{return f.Cause};func Classify(e error)Class{var f Fault;if errors.As(e,&f){return f.Class};return Internal}
